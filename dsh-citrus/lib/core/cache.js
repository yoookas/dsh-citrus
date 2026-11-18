/**
 * 进程内 TTL 缓存。
 *
 * 知乎的正文/评论/热榜都在短时间内不会变，缓存几分钟能明显减少请求数，
 * 也让「看一条内容 + 看它的评论」不会重复拉正文。
 */

export class TtlCache {
  constructor(maxEntries = 256) {
    this.maxEntries = Math.max(1, Number(maxEntries) || 256);
    this.map = new Map();
  }

  get(key, fallback = undefined) {
    const hit = this.map.get(key);
    if (!hit) return fallback;
    if (hit.expiresAt <= Date.now()) {
      this.map.delete(key);
      return fallback;
    }
    // 触碰一下，保持 LRU 顺序
    this.map.delete(key);
    this.map.set(key, hit);
    return hit.value;
  }

  set(key, value, ttlMs) {
    if (!(ttlMs > 0)) return value;
    this.map.set(key, { value, expiresAt: Date.now() + ttlMs });
    while (this.map.size > this.maxEntries) {
      const oldest = this.map.keys().next();
      if (oldest.done) break;
      this.map.delete(oldest.value);
    }
    return value;
  }

  clear() {
    this.map.clear();
  }
}
