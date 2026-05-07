/**
 * HeaderTooltip — column header with a reliable CSS-positioned tooltip on hover.
 *
 * Native `title` attributes are flaky on <th> elements in Chrome, so we render
 * a real tooltip element under the header that fades in on group-hover.
 *
 * Also keeps the native `title` as an accessibility fallback for screen readers.
 */

interface Props {
  name: string;
  tip?: string;
  align?: "left" | "right" | "center";
  className?: string;
}

export default function HeaderTooltip({
  name,
  tip,
  align = "left",
  className = "",
}: Props) {
  const alignClass = align === "right" ? "text-right" : align === "center" ? "text-center" : "";

  return (
    <th className={`relative px-3 py-2 ${alignClass} ${className}`}>
      <span className="group inline-block">
        <span className="cursor-help underline decoration-dotted decoration-gray-600 underline-offset-4">
          {name}
        </span>
        {tip && (
          <span
            role="tooltip"
            className="
              pointer-events-none
              invisible opacity-0
              group-hover:visible group-hover:opacity-100
              transition-opacity duration-150
              absolute left-0 top-full mt-1 z-50
              w-80 max-w-[20rem] p-3
              text-xs font-normal normal-case leading-relaxed
              text-gray-200 bg-bg border border-border rounded shadow-xl
              whitespace-normal text-left
            "
          >
            {tip}
          </span>
        )}
      </span>
    </th>
  );
}
