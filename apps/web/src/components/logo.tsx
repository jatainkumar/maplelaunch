export function MapleMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="#D9480F" />
      <path
        fill="#fff"
        d="M16 5.2l1.9 4.6 2.9-1.2-.9 4.7 4.6-1.4-1.5 3.3 3.1 1-4.4 3.2.9 2.4-5.3-.9-.5 6.3h-1.6l-.5-6.3-5.3.9.9-2.4-4.4-3.2 3.1-1-1.5-3.3 4.6 1.4-.9-4.7 2.9 1.2z"
      />
    </svg>
  );
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <MapleMark className="h-7 w-7" />
      <span className="text-[15px] font-semibold tracking-tight text-zinc-900">
        Maple<span className="text-maple-600">Launch</span>
      </span>
    </span>
  );
}
