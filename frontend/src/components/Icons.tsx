const strokeProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const
};

export function BrandIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.25" {...strokeProps} />
      <path d="M12 3.75c2.6 1.91 4.25 4.92 4.25 8.25S14.6 18.34 12 20.25C9.4 18.34 7.75 15.33 7.75 12S9.4 5.66 12 3.75Z" {...strokeProps} />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
    </svg>
  );
}

export function PanelIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 5.75v12.5" {...strokeProps} />
      <path d="M10 7.5h7.75M10 12h5.75M10 16.5h7.75" {...strokeProps} />
    </svg>
  );
}

export function ComposeIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M13.5 5.75h4.75v4.75" {...strokeProps} />
      <path d="m10.75 13.25 7.5-7.5" {...strokeProps} />
      <path d="M18.25 12v5.25a1 1 0 0 1-1 1H6.75a1 1 0 0 1-1-1V6.75a1 1 0 0 1 1-1H12" {...strokeProps} />
    </svg>
  );
}

export function AttachmentIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m8.75 12.75 5.87-5.87a3 3 0 1 1 4.25 4.24l-7.64 7.64a5 5 0 0 1-7.08-7.08l7.1-7.09" {...strokeProps} />
    </svg>
  );
}

export function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.75 7.25h14.5M9.25 7.25V5.5h5.5v1.75M8.25 10.5v5.75M12 10.5v5.75M15.75 10.5v5.75M6.75 7.25l.7 10.07a1 1 0 0 0 1 .93h7.1a1 1 0 0 0 1-.93l.7-10.07" {...strokeProps} />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M11.75 4.75 19 12l-7.25 7.25" {...strokeProps} />
      <path d="M18.5 12H5" {...strokeProps} />
    </svg>
  );
}

export function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="7.25" y="7.25" width="9.5" height="9.5" rx="2.25" fill="currentColor" />
    </svg>
  );
}

export function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 6.75h5.5M14.5 6.75H19M8.75 6.75a1.75 1.75 0 1 0 0 .01ZM5 12h2.5M11.5 12H19M9.75 12a1.75 1.75 0 1 0 0 .01ZM5 17.25h7.5M16.5 17.25H19M14.25 17.25a1.75 1.75 0 1 0 0 .01Z" {...strokeProps} />
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m6.75 12.25 3.5 3.5 7-7.5" {...strokeProps} />
    </svg>
  );
}

export function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m7 10 5 5 5-5" {...strokeProps} />
    </svg>
  );
}

export function ChevronLeftIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m14 7-5 5 5 5" {...strokeProps} />
    </svg>
  );
}

export function ChevronRightIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m10 7 5 5-5 5" {...strokeProps} />
    </svg>
  );
}
