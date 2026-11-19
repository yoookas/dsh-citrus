/**
 * 一个假的知乎：本地 HTTP 服务，按路径吐固定 JSON。
 *
 * 测试里把 baseUrl 指过来就行 —— 适配器本来就只认 baseUrl。
 */

import { createServer } from 'node:http';

const ANSWER = (targetId = 111, questionId = 222) => ({
  type: 'answer',
  id: targetId,
  question: { id: questionId, title: '这个问题值得读吗？' },
  content: '<p>这是<strong>正文</strong>第一段。</p><p>第二段。</p>',
  excerpt: '这是正文第一段。',
  author: { name: '张三', url_token: 'zhangsan', headline: '写代码的' },
  voteup_count: 1234,
  comment_count: 56,
  created_time: 1700000000,
  updated_time: 1700003600
});

export const SAMPLE = {
  hot: {
    data: [
      {
        card_id: 'Q_123456',
        target: {
          title_area: { text: '如何评价最近的大模型竞赛？' },
          excerpt_area: { text: '几家厂商同时发模型。' },
          metrics_area: { text: '1234 万热度' },
          question: { id: '123456' }
        }
      },
      {
        card_id: 'P_789',
        target: {
          title_area: { text: '一篇讲性能优化的文章' },
          excerpt_area: { text: '从 GC 讲到缓存。' },
          metrics_area: { text: '88 万热度' }
        }
      }
    ]
  },
  search: {
    data: [
      { type: 'relevant_query', object: { type: 'relevant_query' } },
      { type: 'search_result', object: ANSWER(111, 222) },
      {
        type: 'search_result',
        object: {
          type: 'people', id: 'zhangsan', url_token: 'zhangsan',
          name: '张三', headline: '写代码的', follower_count: 4321
        }
      }
    ]
  },
  answer: ANSWER(111, 222),
  question: {
    id: 222,
    title: '这个问题值得读吗？',
    detail: '<p>问题描述。</p>',
    answer_count: 42,
    follower_count: 1000,
    visit_count: 99999,
    created: 1699990000
  },
  questionAnswers: { data: [ANSWER(111, 222), ANSWER(444, 222)] },
  commentsV5: {
    data: [{
      id: '9001',
      content: '<p>说得好。</p>',
      author: { name: '李四', url_token: 'lisi' },
      like_count: 12,
      child_comment_count: 2,
      created_time: 1700000000
    }],
    counts: { total_counts: 1 },
    paging: { is_end: true }
  },
  commentsLegacy: {
    data: [{
      id: 9001,
      content: '<p>说得好。</p>',
      author: { name: '李四', url_token: 'lisi' },
      vote_count: 3,
      reply_count: 2,
      created_time: 1700000000
    }],
    paging: { is_end: true, totals: 1 }
  },
  me: { name: '我', url_token: 'me-self', headline: '测试账号' }
};

export class MockUpstream {
  constructor() {
    this.routes = new Map();
    this.calls = [];
    this.server = createServer((req, res) => this.handle(req, res));
  }

  handle(req, res) {
    const url = new URL(req.url, 'http://127.0.0.1');
    this.calls.push({ path: url.pathname, query: url.search });
    const route = this.routes.get(url.pathname);
    if (!route) {
      res.writeHead(404, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { message: 'not found' } }));
      return;
    }
    const body = typeof route.body === 'function'
      ? JSON.stringify(route.body(url))
      : typeof route.body === 'string' ? route.body : JSON.stringify(route.body);
    res.writeHead(route.status || 200, { 'content-type': route.contentType || 'application/json; charset=utf-8' });
    res.end(body);
  }

  route(path, body, status = 200, contentType = 'application/json; charset=utf-8') {
    this.routes.set(path, { body, status, contentType });
    return this;
  }

  installDefaults() {
    this.route('/api/v3/feed/topstory/hot-lists/total', SAMPLE.hot);
    this.route('/api/v4/search_v3', SAMPLE.search);
    this.route('/api/v4/answers/111', SAMPLE.answer);
    this.route('/api/v4/questions/222', SAMPLE.question);
    this.route('/api/v4/questions/222/answers', SAMPLE.questionAnswers);
    this.route('/api/v4/comment_v5/answers/111/root_comment', SAMPLE.commentsV5);
    this.route('/api/v4/answers/111/comments', SAMPLE.commentsLegacy);
    this.route('/api/v4/articles/333', {
      type: 'article', id: 333, title: '一篇文章',
      content: '<p>文章正文</p>', excerpt: '文章正文',
      author: { name: '李四', url_token: 'lisi' },
      voteup_count: 20, comment_count: 3, created: 1699999999
    });
    this.route('/api/v4/me', SAMPLE.me);
    return this;
  }

  async start() {
    await new Promise((resolve) => this.server.listen(0, '127.0.0.1', resolve));
    const address = this.server.address();
    this.url = 'http://127.0.0.1:' + address.port;
    return this;
  }

  async stop() {
    await new Promise((resolve) => this.server.close(resolve));
  }

  reset() {
    this.calls = [];
  }
}
