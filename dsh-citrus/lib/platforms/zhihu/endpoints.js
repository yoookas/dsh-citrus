/**
 * 知乎的接口地址 —— 平台的所有「魔法字符串」都集中在这一个文件里。
 *
 * 知乎没有面向个人的开放 API，这里用的是网页端自己在用的 v3/v4 只读接口。
 * 接口一改，改这里就够了。
 */

export const BASE_URL = 'https://www.zhihu.com';

export const ANSWER_FIELDS = [
  'content', 'excerpt', 'voteup_count', 'comment_count',
  'author.name', 'author.url_token', 'author.headline', 'author.avatar_url',
  'question.title', 'question.id', 'created_time', 'updated_time'
].join(',');

export const ARTICLE_FIELDS = [
  'content', 'excerpt', 'voteup_count', 'comment_count',
  'author.name', 'author.url_token', 'author.headline', 'author.avatar_url',
  'title', 'created', 'updated'
].join(',');

export const LIST_INCLUDE = 'data[*].content,excerpt,voteup_count,comment_count,author.name,author.url_token,question.title,question.id,created_time';
export const COMMENT_INCLUDE = 'data[*].content,author.name,author.url_token,author.avatar_url,vote_count,created_time,reply_count';

const quote = (value) => encodeURIComponent(String(value));

export function hot(limit) {
  return ['/api/v3/feed/topstory/hot-lists/total', { limit, desktop: 'true' }];
}

export function search(query, limit, offset, kind = '') {
  return ['/api/v4/search_v3', {
    t: kind ? 'content' : 'general',
    q: query,
    correction: 1,
    offset,
    limit: Math.max(1, Math.min(Number(limit) || 20, SEARCH_PAGE_CAP)),
    lc_idx: offset,
    show_all_topics: 0,
    search_source: 'Normal'
  }];
}

export function answer(answerId) {
  return ['/api/v4/answers/' + quote(answerId), { include: ANSWER_FIELDS }];
}

export function article(articleId) {
  return ['/api/v4/articles/' + quote(articleId), { include: ARTICLE_FIELDS }];
}

export function question(questionId) {
  return ['/api/v4/questions/' + quote(questionId), {
    include: 'detail,excerpt,answer_count,follower_count,visit_count,created,updated'
  }];
}

export function questionAnswers(questionId, limit, offset, sortBy = 'default') {
  return ['/api/v4/questions/' + quote(questionId) + '/answers', {
    include: LIST_INCLUDE,
    limit,
    offset,
    sort_by: sortBy
  }];
}

export function pin(pinId) {
  return ['/api/v4/pins/' + quote(pinId), { include: 'content,excerpt,like_count,comment_count,created,updated' }];
}

export function zvideo(zvideoId) {
  return ['/api/v4/zvideos/' + quote(zvideoId), { include: 'title,description,voteup_count,comment_count,created_time' }];
}

export function me() {
  return ['/api/v4/me', { include: 'name,url_token,headline,gender,avatar_url' }];
}

export const COMMENT_NOUNS = {
  answer: 'answers',
  article: 'articles',
  question: 'questions',
  pin: 'pins',
  zvideo: 'zvideos'
};

/** 旧版评论接口每页上限。 */
export const COMMENT_PAGE_LIMIT = 20;
export const SEARCH_PAGE_CAP = 20;

/** 排序参数 -> 上游取值（热度用 normal，时间用 score）。 */
export const COMMENT_ORDERS = { hot: 'normal', new: 'score' };

export function comments(kind, resourceId, limit, offset, sort = 'hot') {
  const noun = COMMENT_NOUNS[kind] || 'answers';
  return ['/api/v4/' + noun + '/' + quote(resourceId) + '/comments', {
    include: COMMENT_INCLUDE,
    limit: Math.max(1, Math.min(Number(limit) || 20, COMMENT_PAGE_LIMIT)),
    offset,
    order: COMMENT_ORDERS[sort] || 'normal'
  }];
}
