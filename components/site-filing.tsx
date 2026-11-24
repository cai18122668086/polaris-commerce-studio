import { currentSiteFiling } from "@/lib/site-filing";

/** 页脚里的运营主体和备案号（备案号未配置时只显示运营主体） */
export function SiteFilingLine({ className }: { className?: string }) {
  const filing = currentSiteFiling();
  return (
    <p className={className} data-site-filing="">
      <span>运营主体：{filing.operator}</span>
      {filing.icp && <a href={filing.icp.href} target="_blank" rel="noopener noreferrer">{filing.icp.number}</a>}
      {filing.psb && <a href={filing.psb.href} target="_blank" rel="noopener noreferrer">{filing.psb.number}</a>}
    </p>
  );
}
