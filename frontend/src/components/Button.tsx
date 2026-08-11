type ButtonProps = {
  children: React.ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "secondary";
  disabled?: boolean;
};

const VARIANT_STYLES: Record<string, React.CSSProperties> = {
  primary: { backgroundColor: "#17594f", color: "#fff" },
  secondary: { backgroundColor: "#fff", color: "#3f4d4e", border: "1px solid #dfe8e9" },
};

export function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  disabled = false,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={VARIANT_STYLES[variant]}
      className="px-4 py-2 rounded-full text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}
