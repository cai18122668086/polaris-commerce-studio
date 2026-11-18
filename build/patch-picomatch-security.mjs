import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";

// Backport the parser-token and nested-alternative fixes in PRs #260, #262, #263.
// https://github.com/micromatch/picomatch/pull/260/commits/d10c0e5003aabed2d81427dd6c125af50bf920ab
// https://github.com/micromatch/picomatch/pull/262/commits/3222059ac27492d9c0147fee5c65f751bbd851ab
// https://github.com/micromatch/picomatch/pull/263/commits/9ca61909ab0ec680953e21bac80a6e825e1ede81
// Picomatch is MIT licensed. See picomatch.LICENSE for the upstream notice.
// Audit recognition verifies the exact patched parser bytes against these hashes.
const parserHashes = {
  "2.3.2": {
    original: "3a91656f440069aa8f8e15c9d695b9f6b2209df1eab2be8127c72cbcca45ff5f",
    patched: "1dd0cf4e8cb48a6e832f9f07265cf04ac0b82175e4a5a42784081140122d07fb",
  },
  "4.0.4": {
    original: "ce57c04e04994b83e2ca566170fa192e6fe19d710bea6da00ce2f76d01c0dea4",
    patched: "5f6a40cfa6d3c7b8cb705eca9e6c2b83f3a9f69c7e5f1e45a84b1419ca10f267",
  },
  "4.0.7": {
    original: "4e1e05447668aa1e94366c5516a2bcd8f5fff800cc92b1d0cd7d77703b8618c4",
    patched: "62808d72424082c04e8ba59f98d9fec2e3cab0a56d98f292e44c6255fafaf44e",
  },
};

export const parserReplacements = [
  [
    "const repeatedExtglobRecursion = pattern => {",
    String.raw`const hasPrefixedNestedQuantifier = branch => {
  let escaped = false;
  let quoted = false;
  let bracket = 0;
  for (let i = 0; i < branch.length; i++) {
    const ch = branch[i];
    if (escaped) { escaped = false; continue; }
    if (ch === '\\') { escaped = true; continue; }
    if (ch === '"') { quoted = !quoted; continue; }
    if (quoted) continue;
    if (ch === '[') { bracket++; continue; }
    if (ch === ']' && bracket) { bracket--; continue; }
    if (!bracket && /[a-zA-Z0-9]/.test(branch[i - 1] || '') &&
        (ch === '*' || ch === '+' || ch === '?') && branch[i + 1] === '(') {
      return true;
    }
  }
  return false;
};
// Collapse nested optional/star extglobs only when the literal alternatives
// already generate every character used by the nested branch. Otherwise the
// nested expression may introduce strings the flat character class cannot.
const safeNestedLiteralClosure = (branches, type) => {
  if (type !== 'plus' && type !== 'star') return;
  const allowed = new Set();
  const nestedWords = [];

  for (const branch of branches) {
    if (/^[a-zA-Z0-9]$/.test(branch)) {
      allowed.add(branch);
      continue;
    }

    const match = /^([a-zA-Z0-9])([*?])\(([a-zA-Z0-9]+)\)$/.exec(branch);
    if (!match) return;
    allowed.add(match[1]);
    nestedWords.push(match[3]);
  }

  if (nestedWords.length === 0 ||
      nestedWords.some(word => [...word].some(char => !allowed.has(char)))) {
    return;
  }

  const chars = [...allowed];
  const alphabet = chars.length === 1 ? chars[0] : '[' + chars.join('') + ']';
  return alphabet + (type === 'plus' ? '+' : '*');
};

// A nested *()/ ?() branch already accepts its own literal prefix when
// the inner quantifier consumes nothing. Repeating an identical literal
// alternative introduces ambiguous partitions and can cause ReDoS.
// Remove only that provably redundant branch; keep other alternatives intact.
const safeRedundantNestedLiteral = (branches, type, options) => {
  if (type !== 'plus' && type !== 'star') return;
  const ignoreCase = options.flags
    ? options.flags.includes('i')
    : options.nocase === true;
  const normalize = value => ignoreCase ? value.toLowerCase() : value;
  let nested;
  const literals = [];

  for (const branch of branches) {
    if (/^[a-zA-Z0-9]+$/.test(branch)) {
      literals.push(branch);
      continue;
    }

    const match = /^([a-zA-Z0-9]+)([*?])\(([a-zA-Z0-9]+)\)$/.exec(branch);
    if (!match || nested) return;
    nested = { prefix: match[1], quantifier: match[2], word: match[3] };
  }

  if (!nested || !literals.some(word =>
    normalize(word) === normalize(nested.prefix))) return;

  const unique = new Map();
  for (const literal of literals) {
    if (normalize(literal) !== normalize(nested.prefix)) {
      unique.set(normalize(literal), literal);
    }
  }
  const remaining = [...unique.values()];
  const tokens = [nested.prefix, ...remaining];

  // When the nested word itself consists entirely of literal alternatives,
  // its repetition adds no new matches. Use the prefix-free literal closure
  // instead of retaining two overlapping repeated alternatives.
  const normalizedWord = normalize(nested.word);
  const reachable = new Set([0]);
  for (let i = 0; i < normalizedWord.length; i++) {
    if (!reachable.has(i)) continue;
    for (const token of tokens) {
      if (normalizedWord.startsWith(normalize(token), i)) {
        reachable.add(i + token.length);
      }
    }
  }

  const prefixFree = tokens.every((token, i) =>
    tokens.every((other, j) => i === j ||
      !normalize(other).startsWith(normalize(token))));
  if (reachable.has(normalizedWord.length)) {
    if (!prefixFree) return;
    return '(?:' + tokens.join('|') + ')' + (type === 'plus' ? '+' : '*');
  }

  // Other branches must begin with distinct characters. Otherwise removing
  // the duplicate prefix would still leave competing branch boundaries.
  const initials = tokens.map(token => normalize(token[0]));
  if (new Set(initials).size !== initials.length) return;

  const inner = nested.prefix + '(?:' + nested.word + ')' + nested.quantifier;
  return '(?:' + [inner, ...remaining].join('|') + ')' + (type === 'plus' ? '+' : '*');
};

const repeatedExtglobRecursion = pattern => {`,
  ],
  [
    "const analyzeRepeatedExtglob = (body, options) => {",
    "const analyzeRepeatedExtglob = (body, options, hasWildcard, type) => {",
  ],
  [
    "  return { risky: false };\n};\n\n/**\n * Parse the given input string.",
    String.raw`  if (hasWildcard) {
    if (!options.capture && branches.length === 1 &&
        /^[A-Za-z0-9 ._-]*\*[A-Za-z0-9 ._-]*$/.test(branches[0])) {
      return { risky: false, collapse: true };
    }

    if (!options.capture && branches.length === 1 && body === branches[0]) {
      const match = /^([A-Za-z0-9_-]+)\*([A-Za-z0-9 ,_-]+)\*$/.exec(body);
      if (match) {
        return { risky: true, twoStars: { prefix: match[1], middle: match[2] } };
      }
    }

    // Disjoint trailing-star alternatives have an unambiguous boundary.
    if (!options.capture && body === branches.join('|')) {
      const wildcards = branches.filter(branch => /^[A-Za-z0-9_-]+\*$/.test(branch));
      const literals = branches.filter(branch => /^[A-Za-z0-9_-]$/.test(branch));
      if (wildcards.length === 1 && literals.length === branches.length - 1 && literals.length > 0) {
        const prefix = wildcards[0].slice(0, -1);
        const nocase = String(options.flags || (options.nocase ? 'i' : '')).includes('i');
        const first = nocase ? prefix[0].toLowerCase() : prefix[0];
        if (!literals.some(value => (nocase ? value.toLowerCase() : value) === first)) {
          return { risky: true, trailingStar: { prefix, literals: [...new Set(literals)].join('') } };
        }
      }
    }

    return { risky: true };
  }

  return { risky: false };
};

/**
 * Parse the given input string.`,
  ],
  [
    "    const analysis = analyzeRepeatedExtglob(body, opts);",
    String.raw`    // Use actual parser tokens so escapes, brackets and options agree.
    const hasWildcard = tokens.slice(token.tokensIndex + 2).some((item, index, bodyTokens) =>
      (item.type === 'star' || item.type === 'globstar') && item.value !== '' &&
      !(bodyTokens[index + 1] && bodyTokens[index + 1].type === 'paren' && bodyTokens[index + 1].value === '(' && bodyTokens[index + 1].extglob === true)
    );
    const analysis = analyzeRepeatedExtglob(body, opts, hasWildcard, token.type);

    if (analysis.twoStars && (token.type === 'plus' || token.type === 'star')) {
      const prefix = utils.escapeRegex(analysis.twoStars.prefix);
      const middle = utils.escapeRegex(analysis.twoStars.middle);
      const unit = opts.bash === true ? '.' : QMARK;
      const tail = opts.bash === true ? '.*?' : STAR;
      const output = prefix + '(?:(?!' + middle + ')' + unit + ')*' + middle + tail;
      analysis.safeOutput = token.type === 'star' ? '(?:' + output + ')?' : output;
    }

    if (analysis.trailingStar && (token.type === 'plus' || token.type === 'star')) {
      const head = '[' + utils.escapeRegex(analysis.trailingStar.literals) + ']';
      const tail = utils.escapeRegex(analysis.trailingStar.prefix) + (opts.bash === true ? '.*?' : STAR);
      analysis.safeOutput = token.type === 'star'
        ? head + '*(?:' + tail + ')?'
        : '(?:' + head + '*' + tail + '|' + head + '+)';
    }`,
  ],
  [
    "  const branches = splitTopLevel(body).map(branch => branch.trim());\n\n  if (branches.length > 1) {",
    String.raw`  const branches = splitTopLevel(body).map(branch => branch.trim());
  const flatNested = safeNestedLiteralClosure(branches, type);
  if (flatNested) {
    return options.capture === true ? { risky: true } : { risky: true, safeOutput: flatNested };
  }
  const redundantNested = safeRedundantNestedLiteral(branches, type, options);
  if (redundantNested) {
    return options.capture === true ? { risky: true } : { risky: true, safeOutput: redundantNested };
  }
  if (type === 'plus' && branches.some(hasPrefixedNestedQuantifier)) {
    return { risky: true };
  }

  if (branches.length > 1) {`,
  ],
  [
    "    let output = token.close + (opts.capture ? ')' : '');",
    String.raw`    if (analysis.collapse === true && (token.type === 'plus' || token.type === 'star')) {
      token.close = token.type === 'plus' ? ')' : ')?';
    }

    let output = token.close + (opts.capture ? ')' : '');`,
  ],
];

export function backportParser(source) {
  for (const [before, after] of parserReplacements) {
    assert.ok(source.includes(before), "Unrecognized picomatch parser source");
    assert.equal(source.indexOf(before), source.lastIndexOf(before), "Ambiguous parser patch");
    source = source.replace(before, after);
  }
  return source;
}

function digest(source) {
  return createHash("sha256").update(source).digest("hex");
}

function installations(root) {
  const lockfile = JSON.parse(readFileSync(path.join(root, "package-lock.json"), "utf8"));
  return Object.entries(lockfile.packages)
    .filter(([name]) => name.endsWith("/picomatch"))
    .map(([name, item]) => {
      const directory = path.resolve(root, name);
      const relative = path.relative(root, directory);
      assert.ok(
        !path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(".." + path.sep),
        "Package path escapes project",
      );
      return { name, version: item.version, directory, hashes: parserHashes[item.version] };
    });
}

export function patchPicomatchSecurity(root) {
  for (const { name, version, directory, hashes } of installations(root)) {
    if (!hashes || !existsSync(directory)) continue;
    const installed = JSON.parse(readFileSync(path.join(directory, "package.json"), "utf8"));
    assert.equal(installed.version, version, `Unexpected installed version in ${name}`);
    const filename = path.join(directory, "lib", "parse.js");
    const original = readFileSync(filename, "utf8");
    const currentHash = digest(original);
    if (currentHash === hashes.patched) continue;
    assert.equal(currentHash, hashes.original, `Unreviewed picomatch source in ${name}`);
    const patched = backportParser(original);
    assert.equal(digest(patched), hashes.patched, `Unexpected patched parser in ${name}`);
    const temporaryFile = filename + ".polaris-" + randomUUID();
    try {
      writeFileSync(temporaryFile, patched, { flag: "wx" });
      renameSync(temporaryFile, filename);
    } finally {
      if (existsSync(temporaryFile)) unlinkSync(temporaryFile);
    }
  }
}

export function verifiedPicomatchPatches(root) {
  const verified = new Set();
  for (const { name, version, directory, hashes } of installations(root)) {
    if (!hashes || !existsSync(directory)) continue;
    const installed = JSON.parse(readFileSync(path.join(directory, "package.json"), "utf8"));
    const source = readFileSync(path.join(directory, "lib", "parse.js"));
    if (installed.version === version && digest(source) === hashes.patched) verified.add(name);
  }
  return verified;
}
