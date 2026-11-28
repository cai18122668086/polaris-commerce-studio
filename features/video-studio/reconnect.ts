/** 断线自动重连的等待时间：2、4、8、16 秒，之后每 30 秒一次（纯函数，node --test 可测）。 */
export function reconnectDelay(attempt: number): number {
  return Math.min(30000, 2000 * 2 ** Math.max(0, attempt));
}
