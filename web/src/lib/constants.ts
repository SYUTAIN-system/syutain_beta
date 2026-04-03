/**
 * SYUTAINβ 共通定数
 */

export const NODE_MODELS: Record<string, { model: string; browser_layer: boolean }> = {
  alpha: { model: "推論なし（Brain-α専用）", browser_layer: false },
  bravo: { model: "Nemotron 9B JP + Qwen3.5-9B", browser_layer: true },
  charlie: { model: "Nemotron 9B JP + Qwen3.5-9B", browser_layer: false },
  delta: { model: "Qwen3.5-4B", browser_layer: false },
};
