import { A } from "@solidjs/router";
import { splitProps, type JSX } from "solid-js";

type ButtonVariant = "default" | "primary" | "danger";
type ButtonSize = "default" | "compact";

type ButtonProps = JSX.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

type ButtonLinkProps = JSX.AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const baseClass =
  "inline-flex cursor-pointer items-center justify-center rounded border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60";

const variantClasses: Record<ButtonVariant, string> = {
  default: "border-gray-600 bg-gray-800 text-gray-100 hover:bg-gray-700",
  primary: "border-sky-600 bg-sky-600 text-white hover:bg-sky-500",
  danger: "border-red-500/40 bg-red-500/10 text-red-200 hover:bg-red-500/20",
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "min-h-9 px-3 py-2 text-sm",
  compact: "min-h-7 px-2 py-1 text-xs",
};

export default function Button(props: ButtonProps) {
  const [local, buttonProps] = splitProps(props, ["variant", "size", "class"]);
  const variant = () => local.variant ?? "default";
  const size = () => local.size ?? "default";

  return (
    <button
      {...buttonProps}
      class={`${baseClass} ${variantClasses[variant()]} ${sizeClasses[size()]} ${local.class ?? ""}`}
    />
  );
}

export function ButtonLink(props: ButtonLinkProps) {
  const [local, linkProps] = splitProps(props, ["variant", "size", "class"]);
  const variant = () => local.variant ?? "default";
  const size = () => local.size ?? "default";

  return (
    <A
      {...linkProps}
      class={`${baseClass} ${variantClasses[variant()]} ${sizeClasses[size()]} ${local.class ?? ""}`}
    />
  );
}
