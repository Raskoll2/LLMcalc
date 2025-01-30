import argparse
import requests
from bs4 import BeautifulSoup
import psutil
import subprocess
import platform
import os
import math

# Quantization bpw values
QUANTIZATION_BPWS = {
    "fp8": 8.0,
    "q6_k_s": 6.6,
    "q5_k_s": 5.5,
    "q4_k_m": 4.8,
    "IQ4_XS": 4.3,
    "q3_k_m": 3.9,
    "IQ3_XS": 3.3,
    "IQ2_XS": 2.4
}

def get_memory_bandwidth():
    """Retrieves system RAM speed in GB/s."""
    try:
        if platform.system() == "Darwin":  # macOS
            # Use system_profiler to detect Apple Silicon model
            cmd = ["system_profiler", "SPHardwareDataType"]
            output = subprocess.check_output(cmd).decode().lower()

            # For Apple Silicon, return the unified memory bandwidth
            # M4 series
            if 'm4 max' in output: return 600  # Theoretical max for M4 Max
            elif 'm4 pro' in output: return 300
            elif 'm4' in output: return 150

            # M3 series
            elif 'm3 max' in output: return 400
            elif 'm3 pro' in output: return 200
            elif 'm3' in output: return 100

            # M2 series
            elif 'm2 max' in output: return 400
            elif 'm2 pro' in output: return 200
            elif 'm2' in output: return 100

            # M1 series
            elif 'm1 ultra' in output: return 800
            elif 'm1 max' in output: return 400
            elif 'm1 pro' in output: return 200
            elif 'm1' in output: return 200

            return 48  # Default fallback for Intel Macs

        elif platform.system() == "Windows":
            cmd = ["powershell", "-Command", "Get-CimInstance Win32_PhysicalMemory | Select-Object -ExpandProperty Speed"]
            output = subprocess.check_output(cmd).decode().strip().split("\n")
            speeds = [int(s) for s in output if s.isdigit()]
            if speeds:
                max_speed = max(speeds)
                return max_speed * 8 * 2 / 1000  # Assuming DDR
            return 48

        elif platform.system() == "Linux":
            try:
                cmd = ["sudo", "dmidecode", "-t", "memory"]
                output = subprocess.check_output(cmd).decode().split("\n")
                speeds = [int(line.split(":")[-1].strip().split(" ")[0])
                         for line in output if "Speed:" in line and "Unknown" not in line]
                if speeds:
                    max_speed = max(speeds)
                    return max_speed * 8 * 2 / 1000
            except:
                # Fallback to /proc/meminfo for basic detection
                with open('/proc/meminfo', 'r') as f:
                    mem_info = f.read()
                    if 'MemTotal' in mem_info:
                        total_gb = int(mem_info.split('MemTotal:')[1].split('kB')[0].strip()) / (1024 * 1024)
                        if total_gb >= 32:
                            return 64  # Assume decent RAM for 32GB+ systems
                        return 48  # Conservative estimate for smaller RAM
            return 48
            
        else: print("Lmao freeBSD user?\n")

    except Exception as e:
        print(f"Error retrieving RAM speed: {e}")
        return 48

def get_model_params(model_id):
    """Scrapes Hugging Face model page to extract model size in params."""
    url = f"https://huggingface.co/{model_id}"
    response = requests.get(url)
    if response.status_code != 200:
        print("Failed to fetch model page.")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    param_divs = soup.find_all('div', class_='inline-flex h-6 shrink-0 items-center overflow-hidden rounded-lg border')

    for div in param_divs:
        if 'Model size' in div.text:
            size_text = div.find_all('div')[1].text.strip()
            return size_text

    return None

def convert_params_to_b(size_text):
    size_text = size_text.lower().replace('params', '').strip()
    if 'b' in size_text:
        return float(size_text.replace('b', '')) * 1e9  # Convert B to actual count
    elif 'm' in size_text:
        return float(size_text.replace('m', '')) * 1e6  # Convert M to actual count
    return None

def get_ram_specs():
    """Retrieves total RAM in GB."""
    try:
        if platform.system() == "Darwin":  # macOS
            cmd = ["system_profiler", "SPMemoryDataType"]
            output = subprocess.check_output(cmd).decode()
            for line in output.split('\n'):
                if 'Memory:' in line and 'GB' in line:
                    # Extract the number before 'GB'
                    ram = float(line.split(':')[1].strip().split('GB')[0].strip())
                    return ram
            # Fallback to sysctl if system_profiler doesn't work
            cmd = ["sysctl", "-n", "hw.memsize"]
            ram_bytes = int(subprocess.check_output(cmd).decode().strip())
            return ram_bytes / 1e9  # Convert to GB
        elif platform.system() == "Linux":
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if 'MemTotal' in line:
                        return int(line.split()[1]) / (1024 * 1024)  # Convert KB to GB
        elif platform.system() == "Windows":
            cmd = ["wmic", "computersystem", "get", "totalphysicalmemory"]
            output = subprocess.check_output(cmd).decode()
            ram_bytes = int(output.split('\n')[1])
            return ram_bytes / 1e9  # Convert to GB

        # Fallback to psutil if platform-specific methods fail
        return psutil.virtual_memory().total / 1e9
    except:
        return psutil.virtual_memory().total / 1e9

def get_vram_specs():
    """Retrieves VRAM size (GB) and bandwidth (GB/s)."""
    vram = None
    bandwidth = None
    brand = None
    num_gpus = 1

    if platform.system() == "Darwin":  # macOS
        try:
            cmd = ["system_profiler", "SPHardwareDataType"]
            output = subprocess.check_output(cmd).decode().lower()

            # For Apple Silicon, treat total RAM as available memory pool
            total_ram = get_ram_specs()

            # Detect chip and set bandwidth
            if 'm4 max' in output:
                bandwidth = 600  # Theoretical max for M4 Max
                vram = total_ram  # All unified memory is available
            elif 'm4 pro' in output:
                bandwidth = 300
                vram = total_ram
            elif 'm4' in output:
                bandwidth = 150
                vram = total_ram
            elif 'm3 max' in output:
                bandwidth = 400
                vram = total_ram
            elif 'm3 pro' in output:
                bandwidth = 200
                vram = total_ram
            elif 'm3' in output:
                bandwidth = 100
                vram = total_ram
            elif 'm2 max' in output:
                bandwidth = 400
                vram = total_ram
            elif 'm2 pro' in output:
                bandwidth = 200
                vram = total_ram
            elif 'm2' in output:
                bandwidth = 100
                vram = total_ram
            elif 'm1 ultra' in output:
                bandwidth = 800
                vram = total_ram
            elif 'm1 max' in output:
                bandwidth = 400
                vram = total_ram
            elif 'm1 pro' in output:
                bandwidth = 200
                vram = total_ram
            elif 'm1' in output:
                bandwidth = 200
                vram = total_ram
            else:
                # Intel Mac - use dedicated GPU if available
                cmd = ["system_profiler", "SPDisplaysDataType"]
                output = subprocess.check_output(cmd).decode().lower()
                if 'radeon' in output or 'vega' in output:
                    vram = 8  # Common size for AMD GPUs in Macs
                    bandwidth = 300
                    brand = "AMD"
                elif 'intel' in output:
                    vram = 4
                    bandwidth = 100
                    brand = "Intel"

            if not brand: brand = "Apple"

        except Exception as e:
            print(f"Error finding VRAM amount: {e}")
            vram = 0
            bandwidth = 0

    elif platform.system() == "Windows":
        try:
            # Check for NVIDIA GPU
            try:
                cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
                output = subprocess.check_output(cmd).decode().strip()
                lines = output.splitlines()
                vrams = [float(line.strip()) for line in lines if line.strip() != ""]
                vram = (sum(vrams) / len(vrams)) / 1024
                brand = "Nvidia"
                num_gpus = len(vrams)
            except:
                pass

            # Check for AMD GPU using PowerShell
            if not vram:
                cmd = ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object AdapterRAM"]
                output = subprocess.check_output(cmd).decode().strip()
                for line in output.split('\n'):
                    if line.strip().isdigit():
                        vram = int(line.strip()) / (1024**3)
                        brand = "AMD"
                        break

            # Check for Intel GPU
            if not vram:
                cmd = ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object Description"]
                output = subprocess.check_output(cmd).decode().lower()
                if 'intel' in output and 'arc' in output:
                    if 'a770' in output: vram = 16
                    elif 'b580' in output: vram = 12
                    elif 'b570' in output: vram = 10
                    elif 'a750' in output: vram = 8
                    elif 'a380' in output: vram = 6
                    elif 'a310' in output: vram = 4
                    else: vram = 0
                    brand = "Intel"
        except:
            print("Error find VRAM amount")
            vram = 0

    elif platform.system() == "Linux":
        try:
            try:
                cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
                output = subprocess.check_output(cmd).decode().strip()
                lines = output.splitlines()
                vrams = [float(line.strip()) for line in lines if line.strip() != ""]
                vram = (sum(vrams) / len(vrams)) / 1024
                brand = "Nvidia"
                num_gpus = len(vrams)
            except:
                pass

            if not vram:
                amd_vram_paths = [
                    "/sys/class/drm/card0/device/mem_info_vram_total",
                    "/sys/class/gpu/card0/device/mem_info_vram_total",
                    "/sys/class/drm/card1/device/mem_info_vram_total",
                    "/sys/class/gpu/card1/device/mem_info_vram_total"
                ]
                options = []
                for path in amd_vram_paths:
                    if os.path.exists(path):
                        with open(path, 'r') as f:
                            options.append(int(f.read().strip()) / 1e9)
                if options != []:
                    vram = max(options)
                    brand = "AMD"

            if not vram:
                cmd = ["lspci", "-v"]
                output = subprocess.check_output(cmd).decode().lower()
                if 'intel' in output and 'arc' in output:
                    if 'a770' in output: vram = 16
                    elif 'b580' in output: vram = 12
                    elif 'b570' in output: vram = 10
                    elif 'a750' in output: vram = 8
                    elif 'a380' in output: vram = 6
                    elif 'a310' in output: vram = 4
                    else: vram = 0
                    brand = "Intel"
        except:
            print("Error find VRAM amount")
            vram = 0

    if platform.system() != "Darwin" and vram:
        if vram >= 49: bandwidth = 1500
        elif vram >= 25: bandwidth = 1790
        elif vram >= 17: bandwidth = 950
        elif vram >= 13: bandwidth = 550
        elif vram >= 9: bandwidth = 400
        elif vram >= 7: bandwidth = 300
        elif vram >= 5: bandwidth = 240
        else: bandwidth = 200

    if not vram: 
        vram = 0
        bandwidth = 0
        brand = "iGPU"

    return vram, bandwidth, num_gpus, brand

def estimate_tks(ram_bandwidth, required_mem):
    """Estimates tk/s for a full RAM offload."""
    return (ram_bandwidth / required_mem) * 0.9

def calculate_tks(base_tks, offload_ratio):

    new_tks = base_tks * (0.052 * math.exp(4.55 * (100-(offload_ratio))/100) + 1.06)
    return new_tks


def fetch_model_config(model_id, params=8):
    try:
        url = f"https://huggingface.co/{model_id}/resolve/main/config.json"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:

        config = {
            "num_hidden_layers": round(-8.58747 + 20.89887 * math.log(params)), # 8 model sample, all different sizes
            "num_key_value_heads": 8, # looks to be standard
            "hidden_size": round(2021.25755 * params**0.352259), # R^2 f 0.98, good enough if not logically sound
            "max_position_embeddings": 131072, # Assume 128k
            "torch_dtype": "bfloat16",
            "num_attention_heads": round(-12.74339 + 21.26379 * math.log(params)), # 8 model sample, all different sizes
        }

        return config

def calculate_max_tokens(available_memory_gb, config):
    num_layers = config.get('num_hidden_layers')
    num_kv_heads = config.get('num_key_value_heads')
    hidden_size = config.get('hidden_size')
    max_position_embeddings = config.get('max_position_embeddings')
    torch_dtype = config.get('torch_dtype', 'bfloat16')

    dtype_to_bytes = {
        'float32': 4,
        'float16': 2,
        'bfloat16': 2,
        'int8': 1
    }
    bytes_per_element = dtype_to_bytes.get(torch_dtype, 2)  # Default to float32 if dtype is unknown

    num_attention_heads = config.get('num_attention_heads')
    head_dim = hidden_size // num_attention_heads

    memory_per_token = num_layers * num_kv_heads * head_dim * 2 * bytes_per_element  # in bytes
    available_memory_bytes = available_memory_gb * (1024 ** 3)
    max_tokens = available_memory_bytes // memory_per_token
    max_tokens = min(max_tokens, max_position_embeddings)

    return max_tokens


def analyze_quantization(params_b, vram_gb, bandwidth, ram_gb, quant, bpw, ram_bandwidth, config_data):
    required_mem = params_b * bpw / 8 / 1e9
    ctx = 0

    if required_mem <= vram_gb:
        if config_data: ctx = calculate_max_tokens(vram_gb - required_mem, config_data)
        base_tks = (bandwidth / required_mem)
        return "All in VRAM", required_mem, 0, base_tks, ctx
    elif required_mem <= vram_gb + 1 and vram_gb > 1:
        if config_data: ctx = calculate_max_tokens(ram_gb+vram_gb - required_mem, config_data)
        base_tks = (bandwidth / required_mem) * 0.9
        return "KV cache offload", required_mem, 0, base_tks, ctx
    elif vram_gb > 1 and required_mem <= (ram_gb + vram_gb):
        if config_data: ctx = calculate_max_tokens(ram_gb+vram_gb - required_mem, config_data)
        offload_ratio = (required_mem - vram_gb) / required_mem * 100
        base_tks = estimate_tks(ram_bandwidth, required_mem)
        return "Partial offload", required_mem, offload_ratio, calculate_tks(base_tks, offload_ratio), ctx
    elif required_mem <= ram_gb:
        if config_data: ctx = calculate_max_tokens(ram_gb - required_mem, config_data)
        base_tks = estimate_tks(ram_bandwidth, required_mem)
        return "All in System RAM", required_mem, 100, base_tks, ctx
    else:
        return "Won't run", required_mem, 0, None, None

def analyze_all_quantizations(params_b, vram_gb, bandwidth, ram_gb, ram_bandwidth, config_data):
    results = {}
    for quant, bpw in QUANTIZATION_BPWS.items():
        run_type, mem_usage, offload_ratio, tks, ctx = analyze_quantization(params_b, vram_gb, bandwidth, ram_gb, quant, bpw, ram_bandwidth, config_data)
        results[quant] = {
            "run_type": run_type,
            "memory_required": mem_usage,
            "offload_percentage": offload_ratio,
            "tk/s": tks,
            "context": ctx,
        }
    return results

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze Hugging Face model with quantization.")
    parser.add_argument("-b", "--bandwidth", type=float, help="Override bandwidth in GB/s.")
    parser.add_argument("-n", "--num-gpus", type=int, help="Number of GPUs.")
    parser.add_argument("-v", "--vram", type=int, help="Amount of VRAM in GB")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    model_id = input("Enter Hugging Face model ID (e.g., microsoft/phi-4): ")
    params_text = get_model_params(model_id)

    if params_text:
        params_b = convert_params_to_b(params_text)
        print(f"Model Parameters: {params_text} ({params_b / 1e9:.2f}B params)")
    else:
        print("Could not determine model parameters.")
        exit()

    config_data = fetch_model_config(model_id, params_b / 1e9)

    total_ram = get_ram_specs()
    print(f"Total RAM: {total_ram:.2f} GB")

    vram, bandwidth, num_gpus, brand = get_vram_specs()
    
    print(f"GPU: {brand}")

    if args.num_gpus: num_gpus = args.num_gpus

    if args.vram:
        vram = args.vram

    if args.bandwidth:
        bandwidth = args.bandwidth

    #if num_gpus > 1:
    #    vram *= num_gpus
    #    bandwidth = (bandwidth*num_gpus) * 0.42 # This is wrong, leads to less total bandwidth the more GPUs you have


    coef = 1
    for i in range(num_gpus):
        bandwidth += bandwidth * coef
        coef = 0.42

    print(f"VRAM: {num_gpus}x{vram:.2f} GB, ~{bandwidth}GB/s total bandwidth")

    ram_bandwidth = get_memory_bandwidth()
    print(f"Estimated RAM Bandwidth: {ram_bandwidth:.2f} GB/s")

    print("\nAnalysis for each quantization level:")
    results = analyze_all_quantizations(params_b, vram*num_gpus, bandwidth, total_ram, ram_bandwidth, config_data)

    for quant, data in results.items():
        print(f"\n{quant.upper()}:")
        print(f"Run Type: {data['run_type']}")
        print(f"Memory Required: {data['memory_required']:.2f} GB")
        if data['offload_percentage'] > 0:
            print(f"GPU Offload Percentage: {100-data['offload_percentage']:.1f}%")
        if data['tk/s']:
            print(f"Estimated tk/s: {data['tk/s']:.2f}")
        if data['context']:
            print(f"Max Context Length: {int(data['context'])} tk")
