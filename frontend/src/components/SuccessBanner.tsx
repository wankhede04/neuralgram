type SuccessBannerProps = {
  message: string;
  onDismiss: () => void;
};

export function SuccessBanner({ message, onDismiss }: SuccessBannerProps) {
  return (
    <div className="mb-4 flex items-start justify-between rounded-[10px] border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
      <span>{message}</span>
      <button onClick={onDismiss} className="ml-4 font-medium text-green-600 hover:text-green-800">
        Dismiss
      </button>
    </div>
  );
}
