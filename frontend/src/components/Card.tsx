type CardProps = {
  children: React.ReactNode;
  className?: string;
};

export function Card({ children, className = "" }: CardProps) {
  return (
    <div
      className={`rounded-[10px] p-6 ${className}`}
      style={{ backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" }}
    >
      {children}
    </div>
  );
}
