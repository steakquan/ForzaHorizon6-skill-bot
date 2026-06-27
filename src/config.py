import os
import json

DEFAULT_CONFIG = {
    "race_duration": 62.0,
    "threshold": 0.8,
    "game_window_title": "Forza Horizon",
    "mastery_grid_topleft": None,
    "mastery_grid_bottomright": None,
    "mastery_car_index": 0
}

def get_config_path(templates_dir="templates"):
    return os.path.join(templates_dir, "config.json")

def load_config(templates_dir="templates"):
    config_path = get_config_path(templates_dir)
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k in data:
                        config[k] = data[k]
        except Exception:
            pass
    return config

def save_config(config_data, templates_dir="templates"):
    config_path = get_config_path(templates_dir)
    try:
        os.makedirs(templates_dir, exist_ok=True)
        # Ensure we only save supported fields
        data_to_save = {}
        for k in DEFAULT_CONFIG.keys():
            if k in config_data:
                data_to_save[k] = config_data[k]
            else:
                data_to_save[k] = DEFAULT_CONFIG[k]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False
