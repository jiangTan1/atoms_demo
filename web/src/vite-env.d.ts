/// <reference types="vite/client" />

// 以 ?inline 引入的样式会作为字符串返回，用于运行时切换代码高亮主题（见 theme/highlight.ts）
declare module '*.css?inline' {
  const css: string;
  export default css;
}