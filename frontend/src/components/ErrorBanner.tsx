type ErrorBannerProps = {
  message: string;
  onDismiss: () => void;
};

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div className="mb-4 flex items-start justify-between rounded-[10px] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <span>{message}</span>
      <button onClick={onDismiss} className="ml-4 font-medium text-red-600 hover:text-red-800">
        Dismiss
      </button>
    </div>
  );
}
