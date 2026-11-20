import { useToastContext } from '../context/ToastContext';

export function useToast() {
  return useToastContext();
}
