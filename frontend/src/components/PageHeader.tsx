type PageHeaderProps = {
  title: string;
  subtitle?: string;
};

export function PageHeader({ title, subtitle }: PageHeaderProps) {
  return (
    <div className="mb-6">
      <h1
        className="text-2xl"
        style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" }}
      >
        {title}
      </h1>
      {subtitle && (
        <p className="mt-1 text-sm" style={{ color: "#5b6a6c" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
