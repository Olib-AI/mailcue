import { cn } from "@/lib/utils";

interface MailCueLogoProps {
  className?: string;
  showBadge?: boolean;
}

function MailCueLogo({ className, showBadge = true }: MailCueLogoProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 120 100"
      fill="none"
      className={cn("shrink-0", className)}
    >
      <defs>
        <clipPath id="mc-env-clip">
          <rect x="10" y="10" width="100" height="76" rx="10" />
        </clipPath>
      </defs>
      <rect x="10" y="10" width="100" height="76" rx="10" fill="#3A7D5C" />
      <g clipPath="url(#mc-env-clip)">
        <path
          d="M10 86 L10 52 L56 73 Q60 75 64 73 L110 52 L110 86 Z"
          fill="#52A97C"
        />
        <path
          d="M10 10 L110 10 L110 48 L64 67 Q60 69 56 67 L10 48 Z"
          fill="#2B5F43"
        />
      </g>
      {showBadge && (
        <>
          <circle
            cx="102"
            cy="16"
            r="15"
            fill="#7FBD8A"
            stroke="white"
            strokeWidth="2.5"
          />
          <path
            d="M94.5 16.5 L99 21 L109.5 11"
            fill="none"
            stroke="white"
            strokeWidth="2.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      )}
    </svg>
  );
}

export { MailCueLogo };
