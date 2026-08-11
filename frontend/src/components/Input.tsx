type InputProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
};

export function Input({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required = false,
}: InputProps) {
  return (
    <label className="block">
      <span className="block text-sm font-medium mb-1" style={{ color: "#3f4d4e" }}>
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full rounded-md border px-3 py-2 text-sm focus:outline-none"
        style={{ borderColor: "#dfe8e9" }}
        onFocus={(e) => (e.currentTarget.style.borderColor = "#17594f")}
        onBlur={(e) => (e.currentTarget.style.borderColor = "#dfe8e9")}
      />
    </label>
  );
}
