import { createSignal, onMount, Show, For } from "solid-js";
import type { Component } from "solid-js";
import type { Settings } from "../types";
import { fetchSettings, saveSettings } from "../api";

interface SettingsModalProps {
  onClose: () => void;
}

const WHISPER_MODELS = [
  "tiny.en",
  "base.en",
  "small.en",
  "medium.en",
  "large-v3",
];

const COMPUTE_TYPES_CPU = ["auto", "int8", "float32"];
const COMPUTE_TYPES_CUDA = ["auto", "int8", "float16", "float32"];

const SettingsModal: Component<SettingsModalProps> = (props) => {
  const [device, setDevice] = createSignal("cpu");
  const [computeType, setComputeType] = createSignal("auto");
  const [model, setModel] = createSignal("base.en");
  const [cudaAvailable, setCudaAvailable] = createSignal(false);
  const [loading, setLoading] = createSignal(true);
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal("");

  onMount(async () => {
    try {
      const settings = await fetchSettings();
      setDevice(settings.whisper_device);
      setComputeType(settings.whisper_compute_type);
      setModel(settings.whisper_model);
      setCudaAvailable(settings.cuda_available);
    } catch (e) {
      setError("Failed to load settings");
    } finally {
      setLoading(false);
    }
  });

  function computeTypes(): string[] {
    return device() === "cuda" ? COMPUTE_TYPES_CUDA : COMPUTE_TYPES_CPU;
  }

  function handleDeviceChange(newDevice: string): void {
    setDevice(newDevice);
    if (!computeTypes().includes(computeType())) {
      setComputeType("auto");
    }
  }

  async function handleSave(): Promise<void> {
    setSaving(true);
    setError("");
    try {
      const updated = await saveSettings({
        whisper_device: device(),
        whisper_compute_type: computeType(),
        whisper_model: model(),
      });
      setDevice(updated.whisper_device);
      setComputeType(updated.whisper_compute_type);
      setModel(updated.whisper_model);
      props.onClose();
    } catch (e: any) {
      setError(e.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      class="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && props.onClose()}
    >
      <div class="modal">
        <div class="modal-header">Transcription Settings</div>
        <div class="modal-body">
          <Show when={!loading()} fallback={<p class="settings-loading-text">Loading...</p>}>
            <div class="modal-field-row">
              <span class="modal-field-label">Device:</span>
              <select
                class="settings-select"
                value={device()}
                onChange={(e) => handleDeviceChange(e.currentTarget.value)}
                disabled={saving()}
              >
                <option value="cpu">CPU</option>
                <Show when={cudaAvailable()}>
                  <option value="cuda">CUDA (GPU)</option>
                </Show>
              </select>
            </div>
            <div class="modal-field-row">
              <span class="modal-field-label">Compute:</span>
              <select
                class="settings-select"
                value={computeType()}
                onChange={(e) => setComputeType(e.currentTarget.value)}
                disabled={saving()}
              >
                <For each={computeTypes()}>
                  {(ct) => <option value={ct}>{ct}</option>}
                </For>
              </select>
            </div>
            <div class="modal-field-row">
              <span class="modal-field-label">Model:</span>
              <select
                class="settings-select"
                value={model()}
                onChange={(e) => setModel(e.currentTarget.value)}
                disabled={saving()}
              >
                <For each={WHISPER_MODELS}>
                  {(m) => <option value={m}>{m}</option>}
                </For>
              </select>
            </div>
            <Show when={error()}>
              <p class="settings-error">{error()}</p>
            </Show>
          </Show>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={props.onClose} disabled={saving()}>
            Cancel
          </button>
          <button
            class="btn-create"
            onClick={handleSave}
            disabled={loading() || saving()}
          >
            {saving() ? "Applying..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
