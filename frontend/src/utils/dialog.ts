import { createVNode, nextTick, render } from 'vue';
import CtDialog from '../components/base/CtDialog.vue';

export interface DialogOptions {
  title?: string;
  message: string;
  type?: 'info' | 'warning' | 'error' | 'wechat_upgrade';
  confirmText?: string;
  cancelText?: string;
  detectedPath?: string;
  detectedAccounts?: string;
  quickLinkUrl?: string;
  quickLinkTitle?: string;
}

export function showDialog(options: DialogOptions | string): Promise<void> {
  return new Promise((resolve) => {
    const opts: DialogOptions =
      typeof options === 'string' ? { title: '提示', message: options } : options;
    const title = opts.title || '提示';

    const container = document.createElement('div');
    document.body.appendChild(container);

    const removeDialog = () => {
      render(null, container);
      container.remove();
      resolve();
    };

    const vnode = createVNode(CtDialog, {
      title,
      message: opts.message,
      type: opts.type,
      confirmText: opts.confirmText,
      cancelText: opts.cancelText,
      detectedPath: opts.detectedPath,
      detectedAccounts: opts.detectedAccounts,
      quickLinkUrl: opts.quickLinkUrl,
      quickLinkTitle: opts.quickLinkTitle,
      onConfirm: () => {
        removeDialog();
      },
      onCancel: () => {
        removeDialog();
      },
    });

    render(vnode, container);
    nextTick(() => {
      vnode.component?.exposed?.open();
    });
  });
}

export function showConfirm(options: DialogOptions | string): Promise<boolean> {
  return new Promise((resolve) => {
    const opts: DialogOptions =
      typeof options === 'string' ? { title: '确认操作', message: options } : options;
    const title = opts.title || '确认操作';

    const container = document.createElement('div');
    document.body.appendChild(container);

    const removeDialog = () => {
      render(null, container);
      container.remove();
    };

    const vnode = createVNode(CtDialog, {
      title,
      message: opts.message,
      type: opts.type || 'warning',
      confirmText: opts.confirmText,
      cancelText: opts.cancelText,
      showCancel: true,
      onConfirm: () => {
        removeDialog();
        resolve(true);
      },
      onCancel: () => {
        removeDialog();
        resolve(false);
      },
    });

    render(vnode, container);
    nextTick(() => {
      vnode.component?.exposed?.open();
    });
  });
}
