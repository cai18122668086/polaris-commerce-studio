# Source observation projection for native identity

The model wire protocol now supplies one ordered, source-bound observation list instead of independently generating a second identity invariant list. The adapter copies those exact texts into the native identity after validating the wire schema, then applies all existing native source, geometry, user-identity and brand checks.

The explicit `ORDERED_SOURCE_OBSERVATIONS_V1` marker authorizes this representation. Wire identity objects cannot contain an independently authored `invariant_features` list. The adapter preserves original payloads and raw model replies in the existing immutable intake journal, and binds the projection receipt to the original payload, observation list and resulting invariants by SHA-256.

Legacy replies remain unchanged and still fail on invariant/observation disagreement. Missing observations, generic preservation rules, wrong product sources, duplicate observation roles, unsupported projection markers and independently supplied invariant lists remain errors. User-supplied product name/category and explicit brandless confirmation are literal output-schema values.

Validation: 45 intake/projection/receipt cases passed, including the public planning flow from an original wire reply through the exact native approval. Mypy passed for 113 application sources after adding the schema result type annotation. No real visual acceptance is claimed by these offline checks.

For the explicit wire protocol, zero uploaded style sources canonically imply an empty reference-analysis list. An omitted/null list is represented as `[]` only in that case. Existing analyses are never removed, and a supplied style source still requires its original analysis. Original wire bytes remain in the journal; both original and canonical payload digests are retained in the projection receipt. The model output schema also declares this list explicitly.

The final intake/projection set passed 49 cases. The exact original V10 model reply passed every current intake guard during a separate offline replay with this zero-reference conversion; that replay made no supplier request and did not update its failed job.
