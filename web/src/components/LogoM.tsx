/**
 * MetaSift logo mark. Straight img ref — the mockup in metasift+/MetaSift
 * App.html::LogoM uses the same approach (see L202-L210), with the asset
 * shipped under web/public/logo.png so vite serves it from the site root.
 */

export function LogoM({ size = 30 }: { size?: number }) {
  return (
    <img
      src="/logo.png"
      alt="MetaSift"
      width={size}
      height={size}
      className="inline-block select-none"
      draggable={false}
    />
  );
}
