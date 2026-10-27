export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand-lockup" aria-label="极光商绘">
      <span className="brand-mark" aria-hidden="true">
        <img src="/polaris-mark.svg" width={40} height={40} alt="" />
      </span>
      {!compact && (
        <span className="brand-copy">
          <strong>极光商绘</strong>
          <small>POLARIS STUDIO</small>
        </span>
      )}
    </div>
  );
}

