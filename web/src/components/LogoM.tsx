/**
 * MetaSift logo mark. Straight img ref to the SVG asset under
 * `web/public/logo.svg`. Vite serves it from the site root, so the same
 * file backs every avatar / brand mark in the app.
 *
 * Drop-shadow filter mirrors the `metasift-logo-static.html` reference's
 * `.metasift-logo` class — emerald glow at 6/22 offset/blur, 45% alpha.
 * Applied via inline style so it scales with `size` proportionally
 * (otherwise the glow would feel weak on the 64px Welcome modal mark
 * and overpowering on the 28px message-list avatar).
 */

export function LogoM({ size = 30 }: { size?: number }) {
  // Glow offset/blur scale with logo size so the look stays consistent
  // across the three call sites (28 / 30 / 64).
  const glowBlur = Math.max(6, Math.round(size * 0.4));
  const glowOffset = Math.max(2, Math.round(size * 0.12));
  return (
    <img
      src="/logo.svg"
      alt="MetaSift"
      width={size}
      height={size}
      className="inline-block select-none"
      draggable={false}
      style={{
        filter: `drop-shadow(0 ${glowOffset}px ${glowBlur}px rgba(16, 185, 129, 0.45))`,
      }}
    />
  );
}
