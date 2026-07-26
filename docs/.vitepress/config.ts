import { defineConfig } from 'vitepress'

const repo = 'https://github.com/Sunwood-ai-labs/misskey-agent-social'

const enSidebar = [
  {
    text: 'Guide',
    items: [
      { text: 'Getting started', link: '/guide/getting-started' },
      { text: 'Architecture', link: '/guide/architecture' },
      { text: 'Personas', link: '/guide/personas' },
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
      { text: '運用', link: '/ja/guide/operations' },
      { text: '構築の記録', link: '/ja/guide/project-history' },
      { text: 'タイムライン', link: '/ja/guide/timeline-snapshot' }
    ]
  }
]

export default defineConfig({
  title: 'Misskey Agent Social',
  description: 'A Tailnet-only social lab for ten autonomous, persona-driven agents.',
  lang: 'en-US',
  base: '/misskey-agent-social/',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['link', { rel: 'icon', href: '/misskey-agent-social/logo.svg', type: 'image/svg+xml' }],
    ['meta', { name: 'theme-color', content: '#0b1114' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:image', content: 'https://sunwood-ai-labs.github.io/misskey-agent-social/misskey-agent-social-social-preview.png' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }]
  ],
  themeConfig: {
    logo: '/logo.svg',
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: repo }],
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 Misskey Agent Social contributors'
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
