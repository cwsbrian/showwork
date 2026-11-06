declare module '@report-view' {
  export function renderReport(
    root: HTMLElement,
    page: any,
    hooks: {
      submitChoice(choiceId: string): Promise<void>;
      assetUrl(relativePath: string): string;
      connected(): boolean;
      idPrefix?: string;
      unavailableText?: string;
    },
  ): { destroy(): void; refresh(): void };
}
declare module '@report-view.css';
declare module '*.css';
