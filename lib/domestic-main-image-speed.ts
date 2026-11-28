// 主图六件套只有一个版本（native_fast：一次规划、六张并行生成）。
// "standard" 只用于展示和恢复改版前创建的旧任务。
export type MainImageSpeed = "standard" | "native_fast";

export function mainImageSpeed(value: unknown): MainImageSpeed {
  return value === "native_fast" ? value : "standard";
}

// Omit the standard default so legacy request identities remain unchanged.
export function mainImageSpeedSettings(speed: MainImageSpeed): { main_image_speed?: Exclude<MainImageSpeed, "standard"> } {
  return speed === "standard" ? {} : { main_image_speed: speed };
}
