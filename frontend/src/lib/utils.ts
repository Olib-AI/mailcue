import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind CSS classes with clsx and tailwind-merge.
 * Handles conditional classes and resolves Tailwind conflicts.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a date string to a human-readable relative or absolute format.
 * - Today: "2:30 PM"
 * - This year: "Feb 28"
 * - Other: "Feb 28, 2025"
 */
export function formatEmailDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();

  if (isToday) {
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }

  const isThisYear = date.getFullYear() === now.getFullYear();
  if (isThisYear) {
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  }

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Format a full date for the email detail header.
 */
export function formatFullDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/**
 * Format file size in bytes to human-readable string.
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = bytes / Math.pow(1024, i);
  const unitLabel = units[i];
  if (!unitLabel) return `${bytes} B`;
  return `${size.toFixed(size < 10 ? 1 : 0)} ${unitLabel}`;
}

/**
 * Format an email address string for display.
 * Accepts a flat string like "John <john@example.com>" or "john@example.com"
 * and returns it as-is (already formatted by the backend).
 */
export function formatEmailAddress(addr: string): string {
  return addr;
}

/**
 * Extract a display name from a flat email address string.
 * - "John <john@example.com>" -> "John"
 * - "john@example.com" -> "john@example.com"
 */
export function extractDisplayName(addr: string): string {
  const match = addr.match(/^(.+?)\s*<.+>$/);
  if (match?.[1]) {
    return match[1].trim();
  }
  return addr;
}

/**
 * Truncate a string to a maximum length with ellipsis.
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength - 1) + "\u2026";
}

/**
 * Generate initials from a name or email address.
 */
export function getInitials(nameOrEmail: string): string {
  if (!nameOrEmail) return "?";

  // If it looks like an email, use the local part
  const name = nameOrEmail.includes("@")
    ? nameOrEmail.split("@")[0] ?? nameOrEmail
    : nameOrEmail;

  const parts = name.split(/[\s._-]+/);
  if (parts.length >= 2) {
    const first = parts[0]?.[0] ?? "";
    const second = parts[1]?.[0] ?? "";
    return (first + second).toUpperCase();
  }
  return (name.slice(0, 2) ?? "").toUpperCase();
}
