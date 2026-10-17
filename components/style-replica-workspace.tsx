"use client";

import {
  Check,
  CheckCircle2,
  ImagePlus,
  Link2,
  LoaderCircle,
  Maximize2,
  RotateCcw,
  Save,
  Sparkles,
  ShieldAlert,
  Store,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import styles from "./style-replica-workspace.module.css";
import { uniqueProductImages } from "../lib/product-image-utils";

type Product = {
  platform: string;
  numIid: string | null;
  tmall: boolean;
  title: string | null;
  price: string | null;
  shopName: string | null;
  sales: string | null;
  imageUrls: string[];
  descImageUrls: string[];
  skuImageUrls?: string[];
  skuPropGroups?: { name: string; values: string[] }[];
  skus?: { sku_id: string; price?: string | null; stock?: string | null }[];
  platformData?: { minimumOrderQuantity?: string | null };
  services: string[];
  warnings?: string[];
};
const demo: Product = {
  platform: "taobao",
  numIid: "981818232043",
  tmall: false,
  title: "JIKOO【小狗】韩系灰色厚棉T外套女秋冬季宽松毛毛领连帽加绒上衣",
  price: "458.00",
  shopName: "JIKOO",
  sales: "已售 38",
  imageUrls: [],
  descImageUrls: [],
  services: ["48 小时内发货", "免运费", "7 天无理由退货"],
};
const demoUrl = "https://" + "item.taobao.com/item.htm?id=981818232043";
type EcommercePlatform = "taobao" | "1688" | "jd" | "pinduoduo";
type SitePreview = {
  label: string;
  network: string;
  platform: EcommercePlatform;
} | null;
const classifyUrlPreview = (raw: string): SitePreview => {
  try {
    const host = new URL(raw.trim()).hostname.toLowerCase().replace(/\.$/, "");
    const matches = (domain: string) =>
      host === domain || host.endsWith(`.${domain}`);
    if (matches("tmall.com"))
      return { label: "天猫", network: "国内直连", platform: "taobao" };
    if (matches("taobao.com") || matches("tb.cn"))
      return { label: "淘宝", network: "国内直连", platform: "taobao" };
    if (matches("1688.com"))
      return { label: "1688", network: "国内直连", platform: "1688" };
    if (matches("jd.com") || matches("3.cn") || matches("npcitem.jd.hk"))
      return { label: "京东", network: "国内直连", platform: "jd" };
    if (matches("pinduoduo.com") || matches("yangkeduo.com"))
      return { label: "拼多多", network: "国内直连", platform: "pinduoduo" };
    if (
      [
        "amazon.com",
        "amazon.co.uk",
        "amazon.de",
        "amazon.co.jp",
        "amazon.ca",
        "amazon.in",
      ].some(matches)
    )
      return { label: "亚马逊", network: "独立代理", platform: "taobao" };
    return null;
  } catch {
    return null;
  }
};
export function StyleReplicaWorkspace() {
  const [url, setUrl] = useState("");
  const [product, setProduct] = useState<Product | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"main" | "detail" | "sku">("main");
  const [selected, setSelected] = useState<string[]>([]);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const [riskUrl, setRiskUrl] = useState("");
  const [riskPlatform, setRiskPlatform] = useState<EcommercePlatform | null>(null);
  const [openingRiskPage, setOpeningRiskPage] = useState(false);
  const [session, setSession] = useState<{
    state: string;
    message: string;
    platform?: string;
    profileReady?: boolean;
  }>({ state: "signed_out", message: "尚未登录商品平台。" });
  const urlPreview = classifyUrlPreview(url);
  const sessionPlatform = urlPreview?.platform ?? "taobao";
  const sessionLabel =
    sessionPlatform === "1688"
      ? "1688"
      : sessionPlatform === "jd"
        ? "京东"
        : sessionPlatform === "pinduoduo"
          ? "拼多多"
          : "淘宝";
  useEffect(() => {
    let active = true;
    const read = async () => {
      try {
        const response = await fetch(
          `/api/ecommerce/session/status?platform=${sessionPlatform}`,
        );
        const body = await response.json();
        if (response.status === 403) {
          if (active) {
            setSession({
              state: "permission_required",
              message: "当前账号无电商会话权限，请使用管理员账号或联系管理员。",
            });
          }
          return;
        }
        if (!response.ok) {
          throw new Error(body.detail?.message ?? "电商会话状态暂时不可用。");
        }
        if (active && body.data) setSession(body.data);
      } catch (caught) {
        if (active) {
          setSession({
            state: "unavailable",
            message: caught instanceof Error ? caught.message : "电商会话状态暂时不可用。",
          });
        }
      }
    };
    void read();
    const timer = window.setInterval(() => void read(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [sessionPlatform]);
  const images =
    tab === "main"
      ? (product?.imageUrls ?? [])
      : tab === "detail"
        ? (product?.descImageUrls ?? [])
        : (product?.skuImageUrls ?? []);
  const all =
    images.length > 0 && images.every((image) => selected.includes(image));
  const sessionReady = session.state === "ready";
  const sessionNeedsRelogin =
    session.state === "needs_relogin" || session.state === "login_required";
  const sessionProfileDetected =
    Boolean(session.profileReady) && !sessionReady && !sessionNeedsRelogin;
  const sessionRiskControlled = session.state === "risk_controlled";
  const sessionPermissionRequired = session.state === "permission_required";
  useEffect(() => {
    if (!previewSrc) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewSrc(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewSrc]);
  const toggleSelected = (src: string) =>
    setSelected((current) =>
      current.includes(src)
        ? current.filter((item) => item !== src)
        : current.length < 20
          ? [...current, src]
          : current,
    );
  const fetchProduct = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError("");
    setRiskUrl("");
    setRiskPlatform(null);
    try {
      const response = await fetch("/api/ecommerce/fetch-item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim(),
          platform:
            urlPreview?.platform === "1688"
              ? "alibaba1688"
              : urlPreview?.platform === "jd"
                ? "jd"
                : urlPreview?.platform === "pinduoduo"
                  ? "pinduoduo"
                  : "auto",
          includeDescImages: true,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = body.detail;
        if (detail?.code === "RISK_CONTROL_PAGE" && (urlPreview?.platform === "1688" || urlPreview?.platform === "pinduoduo")) {
          setRiskUrl(url.trim());
          setRiskPlatform(urlPreview.platform);
        }
        throw new Error(detail?.message ?? "商品解析失败");
      }
      const data = {
        ...body.data,
        imageUrls: uniqueProductImages(body.data.imageUrls ?? [], { preserveClassifiedNames: true }),
        descImageUrls: uniqueProductImages(body.data.descImageUrls ?? [], { preserveClassifiedNames: true }),
        skuImageUrls: uniqueProductImages(body.data.skuImageUrls ?? [], { preserveClassifiedNames: true }),
      } as Product;
      setProduct(data);
      setPreviewSrc(
        data.imageUrls[0] ??
          data.descImageUrls[0] ??
          data.skuImageUrls?.[0] ??
          null,
      );
      setSelected([]);
      setTab("main");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "商品解析失败");
    } finally {
      setLoading(false);
    }
  };
  const openRiskVerificationPage = async () => {
    if (!riskUrl) return;
    setOpeningRiskPage(true);
    setError("");
    try {
      const response = await fetch("/api/ecommerce/session/open-page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: riskPlatform === "pinduoduo" ? "pinduoduo" : "1688", url: riskUrl }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.detail?.message ?? `无法打开${riskPlatform === "pinduoduo" ? "拼多多" : "1688"}官方验证页面`);
      }
      setSaved(
        `已打开${riskPlatform === "pinduoduo" ? "拼多多" : "1688"}官方验证页面。请在弹出的窗口中手动完成验证，完成后回到这里重新拉取。`,
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : `无法打开${riskPlatform === "pinduoduo" ? "拼多多" : "1688"}官方验证页面`,
      );
    } finally {
      setOpeningRiskPage(false);
    }
  };

  const startLogin = async () => {
    setError("");
    const label = sessionLabel;
    try {
      const response = await fetch("/api/ecommerce/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim() || null,
          platform: sessionPlatform,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? `无法启动${label}登录`);
      if (body.data) setSession(body.data);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : `无法启动${label}登录`,
      );
    }
  };
  return (
    <div className={styles.page}>
      <div className={styles.main}>
        <header className={styles.header}>
          <div>
            <span className={styles.eyebrow}>电商工作流 · 多平台商品抓取</span>
            <h1>商品复刻</h1>
            <p>输入商品链接，提取商品图片与规格，选择需要复刻的素材。</p>
          </div>
          <div className={styles.session}>
            <span
              className={
                sessionReady
                  ? styles.status
                  : sessionRiskControlled
                    ? styles.statusRisk
                    : styles.statusMuted
              }
            >
              {sessionRiskControlled || sessionPermissionRequired ? <ShieldAlert size={15} /> : <CheckCircle2 size={15} />}
              {sessionReady
                ? `${sessionLabel}会话已连接`
                : sessionRiskControlled
                  ? `${sessionLabel}安全验证拦截`
                  : sessionPermissionRequired
                    ? "当前账号无电商会话权限"
                  : sessionNeedsRelogin
                    ? `需要重新登录${sessionLabel}`
                  : sessionProfileDetected
                    ? `已检测到${sessionLabel}浏览器会话`
                    : `需要${sessionLabel}授权会话`}
            </span>
            <button
              className={styles.loginButton}
              onClick={() => void startLogin()}
              disabled={session.state === "login_pending" || sessionReady || sessionPermissionRequired}
            >
              {sessionReady
                ? "已连接"
                : sessionNeedsRelogin
                  ? `重新登录${sessionLabel}`
                : sessionProfileDetected
                  ? "验证会话"
                  : session.state === "login_pending"
                  ? "等待登录…"
                  : sessionRiskControlled
                    ? "稍后重试"
                    : sessionPermissionRequired
                      ? "需要管理员权限"
                    : `登录${sessionLabel}`}
            </button>
            {(sessionRiskControlled || sessionPermissionRequired) && (
              <div className={styles.sessionNotice}>
                {session.message || "请停止连续重试，稍后使用稳定网络通过官方页面完成验证。"}
              </div>
            )}
          </div>
        </header>
        <section className={styles.card}>
          <div className={styles.cardTitle}>
            <span className={styles.step}>1</span>
            <div>
              <h2>粘贴商品链接</h2>
              <p>粘贴商品链接后，系统会自动识别平台并选择固定网络策略。</p>
            </div>
          </div>
          <div className={styles.urlRow}>
            <div className={styles.input}>
              <Link2 size={18} />
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="粘贴淘宝、天猫、1688、京东或拼多多商品详情页链接"
              />
            </div>
            {url.trim() && (
              <div className={urlPreview ? styles.status : styles.statusMuted}>
                {urlPreview
                  ? `已识别为：${urlPreview.label} · ${urlPreview.network}`
                  : "暂未识别的平台链接"}
              </div>
            )}
            <button
              className={styles.primary}
              onClick={() => void fetchProduct()}
              disabled={loading || !url.trim()}
            >
              {loading ? (
                <LoaderCircle className="spin" size={17} />
              ) : (
                <Sparkles size={17} />
              )}{" "}
              {loading ? "解析中" : "拉取商品"}
            </button>
          </div>
          {error && (
            <div className={styles.error}>
              <X size={16} /> {error}
            </div>
          )}
          {riskUrl && (
            <div className={styles.riskActions}>
              <div>
                <strong>需要完成官方安全验证</strong>
                <span>
                  本次 {riskPlatform === "pinduoduo" ? "拼多多" : "1688"} 商品页返回了官方安全验证页面。
                  请先在官方窗口手动完成验证；如果打开后显示登录页，则按登录失效处理并重新登录。
                </span>
              </div>
              <div className={styles.riskActionButtons}>
                <button
                  className={styles.secondary}
                  onClick={() => void openRiskVerificationPage()}
                  disabled={openingRiskPage}
                >
                  {openingRiskPage ? "正在打开…" : "打开官方验证页"}
                </button>
                <button
                  className={styles.primary}
                  onClick={() => void fetchProduct()}
                  disabled={loading}
                >
                  {loading ? "解析中" : "验证完成后重新拉取"}
                </button>
              </div>
            </div>
          )}
          {!product && (
            <button
              className={styles.demo}
              onClick={() => {
                setProduct(demo);
                setUrl(demoUrl);
              }}
            >
              先用测试商品预览
            </button>
          )}
        </section>
        {product && (
          <>
            <section className={styles.product}>
              <button
                className={styles.visual}
                onClick={() =>
                  setPreviewSrc(
                    product.imageUrls[0] ?? product.descImageUrls[0] ?? null,
                  )
                }
                disabled={
                  !product.imageUrls.length && !product.descImageUrls.length
                }
              >
                {product.imageUrls[0] ? (
                  <img src={product.imageUrls[0]} alt="商品主图预览" />
                ) : (
                  <div className={styles.placeholder}>
                    <ImagePlus size={30} />
                    <span>等待图片预览</span>
                  </div>
                )}
                {(product.imageUrls.length > 0 ||
                  product.descImageUrls.length > 0) && (
                  <span className={styles.visualHint}>
                    <Maximize2 size={13} /> 点击查看大图
                  </span>
                )}
              </button>
              <div>
                <div className={styles.platform}>
                  <Store size={15} />
                  {product.platform === "alibaba1688"
                    ? "1688"
                    : product.platform === "jd"
                      ? "京东"
                      : product.platform === "pinduoduo"
                        ? "拼多多"
                        : product.tmall
                        ? "天猫"
                        : "淘宝"}
                  <span>商品 ID：{product.numIid ?? "未读取"}</span>
                </div>
                <h2>{product.title ?? "未读取商品标题"}</h2>
                <div className={styles.price}>¥ {product.price ?? "—"}</div>
                <div className={styles.meta}>
                  店铺 <b>{product.shopName ?? "未读取"}</b>　销量{" "}
                  <b>{product.sales ?? "未读取"}</b>
                </div>
                {product.platform === "alibaba1688" &&
                  product.platformData?.minimumOrderQuantity && (
                    <div className={styles.meta}>
                      起批量 <b>{product.platformData.minimumOrderQuantity}</b>
                    </div>
                  )}
                {!!product.skuPropGroups?.length && (
                  <div className={styles.meta}>
                    规格{" "}
                    <b>
                      {product.skuPropGroups
                        .map(
                          (group) =>
                            `${group.name}（${group.values.join(" / ")}）`,
                        )
                        .join(" · ")}
                    </b>
                    　SKU <b>{product.skus?.length ?? 0}</b>
                  </div>
                )}
                <div className={styles.tags}>
                  {product.services.map((service) => (
                    <span key={service}>{service}</span>
                  ))}
                </div>
                {!!product.warnings?.length && (
                  <div className={styles.warningList}>
                    {product.warnings.map((warning) => (
                      <span key={warning}>{warning}</span>
                    ))}
                  </div>
                )}
              </div>
            </section>
            <section className={styles.card}>
              <div className={styles.cardTitle}>
                <span className={styles.step}>2</span>
                <div>
                  <h2>选择复刻图片</h2>
                  <p>
                    点击图片查看大图，使用左上角勾选；最多选择 20 张，已选择{" "}
                    <b>{selected.length}</b> 张。
                  </p>
                </div>
                <button
                  className={styles.selectAll}
                  onClick={() =>
                    setSelected(
                      all ? [] : [...new Set([...selected, ...images])],
                    )
                  }
                >
                  {all ? "取消全选" : "全选当前"}
                </button>
              </div>
              <div className={styles.tabs}>
                <button
                  className={tab === "main" ? styles.active : ""}
                  onClick={() => setTab("main")}
                >
                  主图 <b>{product.imageUrls.length}</b>
                </button>
                <button
                  className={tab === "detail" ? styles.active : ""}
                  onClick={() => setTab("detail")}
                >
                  详情图 <b>{product.descImageUrls.length}</b>
                </button>
                <button
                  className={tab === "sku" ? styles.active : ""}
                  onClick={() => setTab("sku")}
                >
                  SKU图 <b>{product.skuImageUrls?.length ?? 0}</b>
                </button>
              </div>
              {images.length ? (
                <div className={styles.grid}>
                  {images.map((src, index) => (
                    <div
                      key={src}
                      className={`${styles.tile} ${selected.includes(src) ? styles.selected : ""}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => setPreviewSrc(src)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ")
                          setPreviewSrc(src);
                      }}
                    >
                      <img
                        src={src}
                        alt={`商品图 ${index + 1}`}
                        loading="lazy"
                      />
                      <button
                        className={styles.tileCheck}
                        aria-label={
                          selected.includes(src)
                            ? `取消选择商品图 ${index + 1}`
                            : `选择商品图 ${index + 1}`
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleSelected(src);
                        }}
                      >
                        {selected.includes(src) ? (
                          <Check size={14} />
                        ) : (
                          index + 1
                        )}
                      </button>
                      <button
                        className={styles.tileZoom}
                        aria-label={`放大查看商品图 ${index + 1}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setPreviewSrc(src);
                        }}
                      >
                        <Maximize2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={styles.empty}>
                  <ImagePlus size={25} />
                  <p>当前页面没有读取到图片，可稍后重试。</p>
                </div>
              )}
            </section>
            <footer className={styles.footer}>
              <div>
                <strong>{selected.length} 张图片待处理</strong>
                <span>原始链接、商品 ID 和来源平台会一并记录</span>
              </div>
              <div className={styles.footerActions}>
                <button
                  onClick={() => {
                    setProduct(null);
                    setSelected([]);
                    setPreviewSrc(null);
                  }}
                >
                  <RotateCcw size={15} />
                  清空
                </button>
                <button
                  className={styles.secondary}
                  type="button"
                  disabled
                  title="保存到素材库尚未接入"
                >
                  <Save size={15} />
                  保存到素材库（待接入）
                </button>
                <button
                  className={styles.primary}
                  type="button"
                  disabled
                  title="商品复刻 Skill 尚未接入"
                >
                  <Sparkles size={15} />
                  开始复刻（待接入）
                </button>
              </div>
              <p className={styles.saved} role="status">
                当前页面仅支持商品抓取预览；素材保存与复刻任务尚未接入对应 Skill。
                {sessionPermissionRequired ? ` ${session.message}` : ""}
              </p>
              {saved && <div className={styles.saved}>{saved}</div>}
            </footer>
          </>
        )}
      </div>
      <aside className={styles.help}>
        <Sparkles size={20} />
        <h3>商品复刻怎么用？</h3>
        <p>
          粘贴国内电商商品详情页，系统会自动识别平台并使用固定网络策略；当前已接入淘宝
          / 天猫 / 1688 / 京东 / 拼多多。
        </p>
        <div>✓ 图片按主图 / 详情图分组</div>
        <div>✓ 点击图片查看高清大图</div>
        <div>✓ 最多选择 20 张进入复刻</div>
      </aside>
      {previewSrc && (
        <div
          className={styles.lightbox}
          role="dialog"
          aria-modal="true"
          aria-label="商品图片预览"
          onClick={() => setPreviewSrc(null)}
        >
          <button
            className={styles.closePreview}
            aria-label="关闭大图"
            onClick={() => setPreviewSrc(null)}
          >
            <X size={22} />
          </button>
          <img
            src={previewSrc}
            alt="商品大图"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}
