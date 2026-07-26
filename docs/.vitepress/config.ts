import { defineConfig } from 'vitepress'

const repo = 'https://github.com/Sunwood-ai-labs/agent-zero-civilization'

const enSidebar = [
  {
    text: 'Guide',
    items: [
      { text: 'Getting started', link: '/guide/getting-started' },
      { text: 'Architecture', link: '/guide/architecture' },
      { text: 'Personas', link: '/guide/personas' },
      { text: 'Civilization experiment', link: '/guide/civilization-experiment' },
      { text: 'Operations', link: '/guide/operations' },
      { text: 'Project history', link: '/guide/project-history' },
      { text: 'Timeline snapshot', link: '/guide/timeline-snapshot' }
    ]
  }
]

const jaSidebar = [
  {
    text: 'ガイド',
    items: [
      { text: 'はじめる', link: '/ja/guide/getting-started' },
      { text: 'アーキテクチャ', link: '/ja/guide/architecture' },
      { text: '登場人物', link: '/ja/guide/personas' },
      { text: '文明実験', link: '/ja/guide/civilization-experiment' },
      { text: '運用', link: '/ja/guide/operations' },
      { text: '構築の記録', link: '/ja/guide/project-history' },
      { text: 'タイムライン', link: '/ja/guide/timeline-snapshot' }
    ]
  }
]

export default defineConfig({
  title: 'Agent Zero Civilization',
  description: 'Ten autonomous agents begin a civilization from a shared blank basin.',
  lang: 'en-US',
  base: '/agent-zero-civilization/',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['link', { rel: 'icon', href: '/agent-zero-civilization/logo.svg', type: 'image/svg+xml' }],
    ['meta', { name: 'theme-color', content: '#0b1114' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:image', content: 'https://sunwood-ai-labs.github.io/agent-zero-civilization/agent-zero-civilization-social-preview.png' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }]
  ],
  themeConfig: {
    logo: '/logo.svg',
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: repo }],
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 Agent Zero Civilization contributors'
    }
  },
  locales: {
    root: {
      label: 'English',
      lang: 'en-US',
      link: '/',
      themeConfig: {
        nav: [
          { text: 'Guide', link: '/guide/getting-started' },
          { text: 'Architecture', link: '/guide/architecture' },
          { text: 'Personas', link: '/guide/personas' }
        ],
        sidebar: enSidebar,
        outline: { label: 'On this page' },
        docFooter: { prev: 'Previous', next: 'Next' },
        lastUpdated: { text: 'Last updated' }
      }
    },
    ja: {
      label: '日本語',
      lang: 'ja-JP',
      link: '/ja/',
      themeConfig: {
        nav: [
          { text: 'ガイド', link: '/ja/guide/getting-started' },
          { text: '構成', link: '/ja/guide/architecture' },
          { text: '登場人物', link: '/ja/guide/personas' }
        ],
        sidebar: jaSidebar,
        outline: { label: 'このページの内容' },
        docFooter: { prev: '前へ', next: '次へ' },
        lastUpdated: { text: '最終更新' }
      }
    }
  }
})
