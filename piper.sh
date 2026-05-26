#!/bin/bash
sleep 30
# 1. Determine the location of the script and the target directory
SCRIPT_DIR=$(dirname "$0")  # Directory where this script resides
TARGET_DIR="$SCRIPT_DIR" # Set target to the same dir as the script initially

# 2. Find the 'piper_sdk_PICO' directory by walking up the tree
while true; do
    if [ -d "$TARGET_DIR/demo/meshcat" ] && [ -f "$TARGET_DIR/demo/meshcat/piper_web.py" ]; then
        echo "Found piper_sdk_PICO structure at: $TARGET_DIR"
        break # Found the correct location
    fi

    if [ "$TARGET_DIR" = "/" ]; then
        echo "Error: Could not find 'demo/meshcat' directory within the script's hierarchy."
        exit 1
    fi

    TARGET_DIR=$(dirname "$TARGET_DIR") # Move up one level
done

# 3. Find Conda Executable
CONDA_EXECUTABLE=$(command -v conda 2>/dev/null || true)

if [ -z "$CONDA_EXECUTABLE" ]; then
    for CONDA_DIR in \
        "$HOME/miniforge3" \
        "$HOME/miniconda3" \
        "$HOME/anaconda3" \
        "/opt/miniforge3" \
        "/opt/miniconda3" \
        "/opt/anaconda3" \
        "/usr/local/miniforge3" \
        "/usr/local/miniconda3" \
        "/usr/local/anaconda3"; do
        if [ -x "$CONDA_DIR/bin/conda" ]; then
            CONDA_EXECUTABLE="$CONDA_DIR/bin/conda"
            break
        fi
    done
fi

if [ -z "$CONDA_EXECUTABLE" ]; then
    echo "Error: Conda not found.  Ensure conda is installed and in your PATH."
    exit 1
fi

# 4. Check for Conda Environment
"$CONDA_EXECUTABLE" env list | grep robotarm > /dev/null 2>&1

if [ $? -ne 0 ]; then
    echo "Error: Conda environment 'robotarm' not found."
    echo "Please create the environment first."
    echo "Example: conda create -n robotarm python=3.12"
    exit 1
fi

# 5. Initialize Conda
eval "$("$CONDA_EXECUTABLE" shell.bash hook)"

# 6. Activate the Conda Environment
conda activate robotarm

# 7. Change to the Correct Directory
echo "Changing directory to: $TARGET_DIR"
cd "$TARGET_DIR" || { echo "Failed to change directory to $TARGET_DIR"; exit 1; }

# 8. Run the Python script
PYTHON_SCRIPT="demo/meshcat/piper_web.py"

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "Error: Python script $PYTHON_SCRIPT not found."
    exit 1
fi

while true; do
    #python demo/V1/piper_disable.py
    #sleep 5
    python "$PYTHON_SCRIPT"
    echo "Python script exited. Restarting..."
    # Optional: Add a delay before restarting
    # sleep 5
done

# 9. Deactivate the conda environment (optional, unreachable in this loop)
conda deactivate
