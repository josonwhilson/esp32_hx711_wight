import pandas as pd
import numpy as np
from scipy.signal import savgol_filter, medfilt

def optimize_and_clean_data(input_csv, output_csv, x_col, y_col, window_size=51, n_skip=10):
    """
    Standalone data-cleaning pipeline: read -> outlier removal -> denoise/smooth -> downsample -> save
    """
    try:
        print(f"Processing {input_csv}...")
        df = pd.read_csv(input_csv)

        # 1. Basic cleaning: numeric conversion, drop NaN, sort by time
        df[x_col] = pd.to_numeric(df[x_col], errors='coerce')
        df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
        df = df.dropna(subset=[x_col, y_col]).sort_values(by=x_col).reset_index(drop=True)

        x_raw = df[x_col].values
        y_raw = df[y_col].values

        # 2. Robust outlier removal (MAD method)
        median_y = np.median(y_raw)
        mad = np.median(np.abs(y_raw - median_y))
        if mad > 0:
            # Keep points within 5 MAD, drop extreme sensor spikes
            mask = np.abs(y_raw - median_y) < 5 * mad
            x_raw, y_raw = x_raw[mask], y_raw[mask]

        # 3. Denoising / smoothing
        # Median filter first to remove small impulse noise
        y_med = medfilt(y_raw, kernel_size=5)

        # Then Savitzky-Golay smoothing that preserves the trend
        # The window must be odd and no longer than the data
        sw = window_size if window_size % 2 != 0 else window_size + 1
        if sw >= len(y_raw):
            sw = len(y_raw) // 2 * 2 - 1  # shrink the window automatically

        if sw > 3:
            y_smooth = savgol_filter(y_med, window_length=sw, polyorder=2)
        else:
            y_smooth = y_med

        # 4. Uniform downsampling
        x_final = x_raw[::n_skip]
        y_final = y_smooth[::n_skip]

        # 5. Save the result
        df_out = pd.DataFrame({
            x_col: x_final,
            y_col: y_final
        })

        df_out.to_csv(output_csv, index=False)
        print(f"Done! Original points: {len(df)}, points after processing: {len(df_out)}")
        print(f"Result saved to: {output_csv}")

        return df_out

    except Exception as e:
        print(f"Data processing failed: {e}")
        return None

if __name__ == "__main__":
    # Parameter notes:
    # window_size: smoothing window, larger = smoother curve
    # n_skip: downsampling stride, 10 means keep 1 out of every 10 points
    optimize_and_clean_data(
        input_csv="your_data.csv",
        output_csv="cleaned_data.csv",
        x_col="time_s",
        y_col="weight_g",
        window_size=31,
        n_skip=5
    )
