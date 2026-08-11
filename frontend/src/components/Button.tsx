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

const VARIANT_HOVER_BG: Record<string, string> = {
  primary: "#134941",
  secondary: "#f4f9fb",
};

const VARIANT_BASE_BG: Record<string, string> = {
  primary: "#17594f",
  secondary: "#fff",
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
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.backgroundColor = VARIANT_HOVER_BG[variant];
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = VARIANT_BASE_BG[variant];
      }}
      className="px-4 py-2 rounded-full text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}
