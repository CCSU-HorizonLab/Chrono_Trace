import { createVNode, render, AppContext } from 'vue';
import CtDialog from '../components/base/CtDialog.vue';

export interface DialogOptions {
  title?: string;
  message: string;
}

export function showDialog(options: DialogOptions | string): Promise<void> {
  return new Promise((resolve) => {
    let message = typeof options === 'string' ? options : options.message;
    let title = typeof options === 'string' ? '提示' : (options.title || '提示');

    const container = document.createElement('div');
    document.body.appendChild(container);

    const removeDialog = () => {
      render(null, container);
      container.remove();
      resolve();
    };

    const vnode = createVNode(CtDialog, {
      title,
      message,
      onConfirm: () => {
        removeDialog();
      }
    });

    render(vnode, container);

    // After mounting, call the open method to trigger enter animations
    if (vnode.component && vnode.component.exposed) {
      vnode.component.exposed.open();
    }
  });
}

export function showConfirm(options: DialogOptions | string): Promise<boolean> {
  return new Promise((resolve) => {
    let message = typeof options === 'string' ? options : options.message;
    let title = typeof options === 'string' ? '提问' : (options.title || '提问');

    const container = document.createElement('div');
    document.body.appendChild(container);

    const removeDialog = () => {
      render(null, container);
      container.remove();
    };

    const vnode = createVNode(CtDialog, {
      title,
      message,
      showCancel: true,
      onConfirm: () => {
        removeDialog();
        resolve(true);
      },
      onCancel: () => {
        removeDialog();
        resolve(false);
      }
    });

    render(vnode, container);

    if (vnode.component && vnode.component.exposed) {
      vnode.component.exposed.open();
    }
  });
}
