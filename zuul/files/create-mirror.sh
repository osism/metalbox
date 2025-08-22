#!/bin/bash

# Direct Package Download Mirror Script
# Downloads specific packages using direct URL downloads
#
# Environment Variables:
# - PARALLEL_DOWNLOADS: Number of concurrent downloads (default: 10)
# - MIRROR_DIR: Directory for the mirror (default: /tmp/repository)
# - SCRIPT_DIR: Directory containing config files

set -e

# Configuration
SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
REPOSITORIES_CONF="${SCRIPT_DIR}/repositories.conf"
PACKAGES_LIST="${SCRIPT_DIR}/packages.list"
MIRROR_DIR="${MIRROR_DIR:-/tmp/repository}"
LOG_FILE="${SCRIPT_DIR}/mirror.log"
TEMP_DIR="/tmp/mirror-$$"
PARALLEL_DOWNLOADS="${PARALLEL_DOWNLOADS:-10}"

# Performance optimizations
PACKAGES_CACHE_DIR="$TEMP_DIR/packages_cache"
declare -A PACKAGES_METADATA_CACHE

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging function
log() {
    echo -e "$1"
    if [[ -d "$(dirname "$LOG_FILE")" ]]; then
        echo -e "$1" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

error() {
    log "${RED}ERROR: $1${NC}"
    exit 1
}

warning() {
    log "${YELLOW}WARNING: $1${NC}"
}

success() {
    log "${GREEN}SUCCESS: $1${NC}"
}

# Check dependencies
check_dependencies() {
    log "Checking dependencies..."

    local missing_deps=()

    if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
        missing_deps+=("wget or curl")
    fi

    if ! command -v dpkg-scanpackages >/dev/null 2>&1; then
        missing_deps+=("dpkg-dev")
    fi

    if ! command -v gzip >/dev/null 2>&1; then
        missing_deps+=("gzip")
    fi

    if ! command -v xargs >/dev/null 2>&1; then
        missing_deps+=("xargs")
    fi

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        error "Missing dependencies: ${missing_deps[*]}"
    fi

    success "Dependencies check passed"
}

# Read configuration files
read_config() {
    log "Reading configuration files..."

    if [[ ! -f "$REPOSITORIES_CONF" ]]; then
        error "Repository configuration file not found: $REPOSITORIES_CONF"
    fi

    if [[ ! -f "$PACKAGES_LIST" ]]; then
        error "Package list file not found: $PACKAGES_LIST"
    fi

    # Read repositories (skip comments and empty lines)
    REPOSITORIES=($(grep -v '^#' "$REPOSITORIES_CONF" | grep -v '^[[:space:]]*$'))

    # Read packages (skip comments and empty lines)
    PACKAGES=($(grep -v '^#' "$PACKAGES_LIST" | grep -v '^[[:space:]]*$'))

    log "Found ${#REPOSITORIES[@]} repositories and ${#PACKAGES[@]} packages"
    success "Configuration files read successfully"
}

# Download file using wget or curl
download_file() {
    local url="$1"
    local output="$2"

    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$output" "$url" 2>/dev/null
    elif command -v curl >/dev/null 2>&1; then
        curl -s -o "$output" "$url" 2>/dev/null
    else
        return 1
    fi
}

# Parallel download function for a single URL
parallel_download_single() {
    local url="$1"
    local output="$2"
    local temp_log="$3"

    local result=0
    local filename=$(basename "$output")

    echo "    Downloading: $filename" >&2

    if download_file "$url" "$output"; then
        if [[ -f "$output" && -s "$output" ]]; then
            echo "    Downloaded successfully: $filename" >&2
            echo "SUCCESS: $filename" >> "$temp_log"
        else
            echo "    Failed (empty file): $filename" >&2
            echo "FAILED: $filename (empty file)" >> "$temp_log"
            rm -f "$output"
            result=1
        fi
    else
        echo "    Failed (download error): $filename" >&2
        echo "FAILED: $filename (download error)" >> "$temp_log"
        result=1
    fi

    return $result
}

# Download multiple files in parallel
parallel_download_files() {
    local download_dir="$1"
    shift
    local urls=("$@")

    if [[ ${#urls[@]} -eq 0 ]]; then
        return 0
    fi

    log "  Downloading ${#urls[@]} files in parallel (max $PARALLEL_DOWNLOADS concurrent)"

    local temp_log="$TEMP_DIR/download_log_$$.txt"
    > "$temp_log"

    # Create a temporary file with URL and output path pairs
    local url_list="$TEMP_DIR/url_list_$$.txt"
    > "$url_list"

    for url in "${urls[@]}"; do
        local filename=$(basename "$url")
        local output_path="$download_dir/$filename"

        # Skip if file already exists and is not empty (enhanced check)
        if [[ -f "$output_path" && -s "$output_path" ]]; then
            # Verify file is a valid .deb package (basic check)
            if [[ "$filename" == *.deb ]] && ! file "$output_path" 2>/dev/null | grep -q "Debian binary package"; then
                # File exists but is corrupted, remove it
                rm -f "$output_path"
            else
                echo "SKIPPED: $filename (already exists)" >> "$temp_log"
                continue
            fi
        fi

        echo "$url|$output_path" >> "$url_list"
    done

    # Use xargs for parallel downloads (GNU parallel disabled due to argument parsing issues)
    export -f parallel_download_single download_file
    export TEMP_DIR

    cat "$url_list" | xargs -P "$PARALLEL_DOWNLOADS" -I {} bash -c '
        IFS="|" read -r url output <<< "{}"
        parallel_download_single "$url" "$output" "'$temp_log'"
    '

    # Process results
    local success_count=0
    local failed_count=0
    local skipped_count=0

    while IFS= read -r line; do
        if [[ "$line" == SUCCESS:* ]]; then
            success_count=$((success_count + 1))
        elif [[ "$line" == FAILED:* ]]; then
            failed_count=$((failed_count + 1))
            warning "    $line"
        elif [[ "$line" == SKIPPED:* ]]; then
            skipped_count=$((skipped_count + 1))
        fi
    done < "$temp_log"

    log "  Parallel download results: $success_count succeeded, $failed_count failed, $skipped_count skipped"

    # Cleanup
    rm -f "$temp_log" "$url_list"

    return $failed_count
}

# Parallel package lookup function for a single package
parallel_package_lookup() {
    local package="$1"
    local repositories_str="$2"
    local output_file="$3"

    echo "    Looking for package: $package" >&2

    # Convert repositories string back to array
    IFS='|' read -ra repositories <<< "$repositories_str"

    # Find package URLs
    local package_urls=$(find_best_package "$package" "${repositories[@]}")

    if [[ -n "$package_urls" ]]; then
        echo "    Found URLs for package: $package" >&2
        while IFS= read -r package_url; do
            if [[ -n "$package_url" ]]; then
                echo "$package:$package_url" >> "$output_file"
            fi
        done <<< "$package_urls"
    else
        echo "    Package $package not found in any repository" >&2
        echo "NOT_FOUND:$package" >> "$output_file"
    fi
}

# Lookup package URLs in parallel
parallel_package_lookups() {
    local download_dir="$1"
    shift
    local packages=("$@")

    if [[ ${#packages[@]} -eq 0 ]]; then
        return 0
    fi

    log "Looking up ${#packages[@]} packages in parallel (max $PARALLEL_DOWNLOADS concurrent)"

    local lookup_results="$TEMP_DIR/lookup_results_$$.txt"
    > "$lookup_results"

    # Convert REPOSITORIES array to string for passing to subprocesses
    local repositories_str=""
    for repo in "${REPOSITORIES[@]}"; do
        if [[ -n "$repositories_str" ]]; then
            repositories_str="$repositories_str|$repo"
        else
            repositories_str="$repo"
        fi
    done

    # Create a temporary file with packages to lookup
    local package_list="$TEMP_DIR/package_list_$$.txt"
    printf '%s\n' "${packages[@]}" > "$package_list"

    # Export functions and variables needed by subprocesses
    export -f parallel_package_lookup find_best_package find_package_info find_all_package_versions version_compare download_file cache_packages_file
    export TEMP_DIR PACKAGES_CACHE_DIR
    export -A PACKAGES_METADATA_CACHE

    # Use xargs for package lookups (GNU parallel disabled due to argument parsing issues)
    cat "$package_list" | xargs -P "$PARALLEL_DOWNLOADS" -I {} bash -c "
        parallel_package_lookup '{}' '$repositories_str' '$lookup_results'
    "

    # Process results and populate global arrays
    PARALLEL_LOOKUP_URLS=()
    PARALLEL_LOOKUP_NOT_FOUND=()

    while IFS= read -r line; do
        if [[ "$line" == NOT_FOUND:* ]]; then
            local package_name=${line#NOT_FOUND:}
            PARALLEL_LOOKUP_NOT_FOUND+=("$package_name")
            warning "  Package $package_name not found in any repository"
        else
            IFS=':' read -r package_name package_url <<< "$line"
            if [[ -n "$package_name" && -n "$package_url" ]]; then
                local deb_filename=$(basename "$package_url")
                local local_path="$download_dir/$deb_filename"

                # Check if we need to download this file (enhanced validation)
                local need_download=false
                
                if [[ ! -f "$local_path" || ! -s "$local_path" ]]; then
                    need_download=true
                elif [[ "$deb_filename" == *.deb ]] && ! file "$local_path" 2>/dev/null | grep -q "Debian binary package"; then
                    # File exists but is corrupted
                    rm -f "$local_path"
                    need_download=true
                fi
                
                if [[ "$need_download" == true ]]; then
                    PARALLEL_LOOKUP_URLS+=("$package_url")
                else
                    log "    Already have: $deb_filename"
                    # Mark as downloaded since we already have it
                    if [[ ! " ${downloaded_packages[@]} " =~ " ${package_name} " ]]; then
                        downloaded_packages+=("$package_name")
                    fi
                fi
            fi
        fi
    done < "$lookup_results"

    log "  Package lookup results: $((${#packages[@]} - ${#PARALLEL_LOOKUP_NOT_FOUND[@]})) found, ${#PARALLEL_LOOKUP_NOT_FOUND[@]} not found"

    # Cleanup
    rm -f "$lookup_results" "$package_list"

    return 0
}

# Download and cache Packages.gz file
cache_packages_file() {
    local packages_url="$1"
    local cache_key=$(echo "$packages_url" | sed 's|[^a-zA-Z0-9]|_|g')
    local cache_file="$PACKAGES_CACHE_DIR/${cache_key}.gz"
    
    if [[ ! -f "$cache_file" ]]; then
        mkdir -p "$PACKAGES_CACHE_DIR"
        if download_file "$packages_url" "$cache_file" >/dev/null 2>&1; then
            return 0
        else
            rm -f "$cache_file"
            return 1
        fi
    fi
    return 0
}

# Parse Packages file to find package URLs with version info (optimized with caching)
find_package_info() {
    local packages_url="$1"
    local package_name="$2"
    local base_url="$3"

    # Use cached file
    local cache_key=$(echo "$packages_url" | sed 's|[^a-zA-Z0-9]|_|g')
    local cache_file="$PACKAGES_CACHE_DIR/${cache_key}.gz"
    
    if ! cache_packages_file "$packages_url"; then
        return 1
    fi

    # Check metadata cache first (use safe key format)
    local safe_package_name=$(echo "$package_name" | sed 's|[^a-zA-Z0-9]|_|g')
    local cache_lookup_key="${cache_key}_${safe_package_name}"
    if [[ -n "${PACKAGES_METADATA_CACHE[$cache_lookup_key]}" ]]; then
        echo "${PACKAGES_METADATA_CACHE[$cache_lookup_key]}"
        return 0
    fi

    # Extract package info including version
    local package_info=$(zcat "$cache_file" 2>/dev/null | awk -v pkg="$package_name" '
        BEGIN { RS="\n\n"; FS="\n" }
        $1 ~ "^Package: " pkg "$" {
            filename = ""
            version = ""
            for (i=1; i<=NF; i++) {
                if ($i ~ /^Filename: /) {
                    filename = substr($i, 11)
                }
                if ($i ~ /^Version: /) {
                    version = substr($i, 10)
                }
            }
            if (filename != "" && version != "") {
                print version "|" filename
            }
        }
    ')

    if [[ -n "$package_info" ]]; then
        local version=$(echo "$package_info" | cut -d'|' -f1)
        local filename=$(echo "$package_info" | cut -d'|' -f2)
        local result="$version|$base_url/$filename"
        
        # Cache the result
        PACKAGES_METADATA_CACHE[$cache_lookup_key]="$result"
        echo "$result"
    fi
}

# Compare two Debian package versions
version_compare() {
    local version1="$1"
    local version2="$2"

    # Use dpkg --compare-versions if available, otherwise simple string comparison
    if command -v dpkg >/dev/null 2>&1; then
        if dpkg --compare-versions "$version1" gt "$version2" 2>/dev/null; then
            echo "1"  # version1 > version2
        elif dpkg --compare-versions "$version1" eq "$version2" 2>/dev/null; then
            echo "0"  # version1 = version2
        else
            echo "-1" # version1 < version2
        fi
    else
        # Fallback to simple string comparison
        if [[ "$version1" > "$version2" ]]; then
            echo "1"
        elif [[ "$version1" = "$version2" ]]; then
            echo "0"
        else
            echo "-1"
        fi
    fi
}

# Find all versions of a package (for Docker packages)
find_all_package_versions() {
    local package_name="$1"
    local repo_configs=("${@:2}")

    local all_urls=()

    for repo_config in "${repo_configs[@]}"; do
        IFS=':' read -r host path dist components arch <<< "$repo_config"
        local base_url="http://$host$path"

        # Process each component
        IFS=',' read -ra COMP_ARRAY <<< "$components"
        for component in "${COMP_ARRAY[@]}"; do
            local packages_url="$base_url/dists/$dist/$component/binary-$arch/Packages.gz"
            local packages_file="$TEMP_DIR/Packages_$(basename "$packages_url" .gz)_$$.gz"

            if download_file "$packages_url" "$packages_file" >/dev/null 2>&1; then
                # Extract all versions of the package
                local package_infos=$(zcat "$packages_file" 2>/dev/null | awk -v pkg="$package_name" '
                    BEGIN { RS="\n\n"; FS="\n" }
                    $1 ~ "^Package: " pkg "$" {
                        filename = ""
                        version = ""
                        for (i=1; i<=NF; i++) {
                            if ($i ~ /^Filename: /) {
                                filename = substr($i, 11)
                            }
                            if ($i ~ /^Version: /) {
                                version = substr($i, 10)
                            }
                        }
                        if (filename != "" && version != "") {
                            print version "|" filename
                        }
                    }
                ')

                if [[ -n "$package_infos" ]]; then
                    while IFS= read -r package_info; do
                        if [[ -n "$package_info" ]]; then
                            local filename=$(echo "$package_info" | cut -d'|' -f2)
                            all_urls+=("$base_url/$filename")
                        fi
                    done <<< "$package_infos"
                fi

                rm -f "$packages_file"
            fi
        done
    done

    # Remove duplicates and return
    if [[ ${#all_urls[@]} -gt 0 ]]; then
        printf '%s\n' "${all_urls[@]}" | sort -u
    fi
}

# Find best package version across repositories with priority
find_best_package() {
    local package_name="$1"
    local repo_configs=("${@:2}")

    # Docker packages need all versions
    case "$package_name" in
        docker-ce|docker-ce-cli|containerd.io)
            find_all_package_versions "$package_name" "${repo_configs[@]}"
            return
            ;;
    esac

    local best_version=""
    local best_url=""
    local best_priority=999

    # Define repository priorities (lower number = higher priority)
    declare -A repo_priorities=(
        ["noble-security"]=1
        ["noble-updates"]=2
        ["noble"]=3
        ["stable"]=4  # Docker repo
    )

    for repo_config in "${repo_configs[@]}"; do
        IFS=':' read -r host path dist components arch <<< "$repo_config"
        local base_url="http://$host$path"

        # Get priority for this distribution
        local current_priority=${repo_priorities[$dist]:-999}

        # Process each component
        IFS=',' read -ra COMP_ARRAY <<< "$components"
        for component in "${COMP_ARRAY[@]}"; do
            local packages_url="$base_url/dists/$dist/$component/binary-$arch/Packages.gz"
            local package_info=$(find_package_info "$packages_url" "$package_name" "$base_url")

            if [[ -n "$package_info" ]]; then
                local version=$(echo "$package_info" | cut -d'|' -f1)
                local url=$(echo "$package_info" | cut -d'|' -f2)

                # Select this version if:
                # 1. We don't have a version yet, OR
                # 2. This version is newer, OR
                # 3. Same version but higher priority repository
                if [[ -z "$best_version" ]] || \
                   [[ $(version_compare "$version" "$best_version") -eq 1 ]] || \
                   [[ $(version_compare "$version" "$best_version") -eq 0 && $current_priority -lt $best_priority ]]; then
                    best_version="$version"
                    best_url="$url"
                    best_priority="$current_priority"
                fi
            fi
        done
    done

    if [[ -n "$best_url" ]]; then
        echo "$best_url"
    fi
}

# Preload all package metadata for fast dependency resolution
preload_packages_metadata() {
    local repo_configs=("$@")
    declare -gA ALL_PACKAGES_DEPS
    
    log "Preloading package metadata for fast dependency resolution..."
    
    for repo_config in "${repo_configs[@]}"; do
        IFS=':' read -r host path dist components arch <<< "$repo_config"
        local base_url="http://$host$path"
        
        IFS=',' read -ra COMP_ARRAY <<< "$components"
        for component in "${COMP_ARRAY[@]}"; do
            local packages_url="$base_url/dists/$dist/$component/binary-$arch/Packages.gz"
            local cache_key=$(echo "$packages_url" | sed 's|[^a-zA-Z0-9]|_|g')
            
            if cache_packages_file "$packages_url"; then
                local cache_file="$PACKAGES_CACHE_DIR/${cache_key}.gz"
                
                # Parse and cache all dependencies at once
                zcat "$cache_file" 2>/dev/null | awk '
                    BEGIN { RS="\n\n"; FS="\n" }
                    {
                        package = ""
                        depends = ""
                        for (i=1; i<=NF; i++) {
                            if ($i ~ /^Package: /) {
                                package = substr($i, 10)
                            }
                            if ($i ~ /^Depends: /) {
                                depends = substr($i, 10)
                                # Remove version constraints and alternatives
                                gsub(/\([^)]*\)/, "", depends)
                                gsub(/\|[^,]*/, "", depends)
                                gsub(/[ \t]+/, " ", depends)
                            }
                        }
                        if (package != "" && depends != "") {
                            print package ":" depends
                        }
                    }
                ' | while IFS=: read -r pkg deps; do
                    local safe_pkg=$(echo "$pkg" | sed 's|[^a-zA-Z0-9._-]|_|g')
                    ALL_PACKAGES_DEPS["$safe_pkg"]="$deps"
                done
            fi
        done
    done
    
    log "Preloaded metadata for ${#ALL_PACKAGES_DEPS[@]} packages"
}

# Resolve package dependencies from a specific packages file
resolve_dependencies_from_file() {
    local package="$1"
    local packages_file="$2"

    local deps=$(zcat "$packages_file" 2>/dev/null | awk -v pkg="$package" '
        BEGIN { RS="\n\n"; FS="\n" }
        $1 ~ "^Package: " pkg "$" {
            for (i=1; i<=NF; i++) {
                if ($i ~ /^Depends: /) {
                    depends = substr($i, 10)
                    # Remove version constraints and alternatives
                    gsub(/\([^)]*\)/, "", depends)
                    gsub(/\|[^,]*/, "", depends)
                    gsub(/[ \t]+/, " ", depends)
                    print depends
                    break
                }
            }
        }
    ')

    if [[ -n "$deps" ]]; then
        # Split dependencies and clean up
        echo "$deps" | tr ',' '\n' | sed 's/^[ \t]*//;s/[ \t]*$//' | grep -v '^$'
    fi
}

# Download packages from repositories
download_packages() {
    log "Starting package download with dependency resolution..."

    local download_dir="$TEMP_DIR/packages"
    mkdir -p "$download_dir"

    local downloaded_packages=()
    local failed_packages=()
    local packages_to_download=()
    local processed_packages=()

    # Initialize with user-requested packages
    packages_to_download=("${PACKAGES[@]}")

    # Skip preloading (too slow) - use on-demand resolution instead
    # preload_packages_metadata "${REPOSITORIES[@]}"
    
    log "Resolving dependencies for ${#PACKAGES[@]} initial packages..."

    # Process each repository for dependency resolution
    for repo_config in "${REPOSITORIES[@]}"; do
        IFS=':' read -r host path dist components arch <<< "$repo_config"

        local base_url="http://$host$path"
        log "Processing repository: $base_url $dist"

        # Download all Packages.gz files for dependency resolution
        local packages_files=()
        IFS=',' read -ra COMP_ARRAY <<< "$components"
        for component in "${COMP_ARRAY[@]}"; do
            local packages_url="$base_url/dists/$dist/$component/binary-$arch/Packages.gz"
            local packages_file="$TEMP_DIR/Packages_${dist}_${component}_$$.gz"

            if download_file "$packages_url" "$packages_file" >/dev/null 2>&1; then
                packages_files+=("$packages_file")
            fi
        done

        # Resolve dependencies iteratively
        local iteration=0
        local max_iterations=10

        while [[ ${#packages_to_download[@]} -gt 0 && $iteration -lt $max_iterations ]]; do
            iteration=$((iteration + 1))
            log "  Dependency resolution iteration $iteration"

            local new_dependencies=()

            for package in "${packages_to_download[@]}"; do
                # Skip if already processed
                if [[ " ${processed_packages[@]} " =~ " ${package} " ]]; then
                    continue
                fi

                processed_packages+=("$package")
                log "    Resolving dependencies for: $package"

                # Find dependencies in all package files
                for packages_file in "${packages_files[@]}"; do
                    local deps=$(resolve_dependencies_from_file "$package" "$packages_file")
                    if [[ -n "$deps" ]]; then
                        while IFS= read -r dep; do
                            if [[ -n "$dep" && ! " ${processed_packages[@]} " =~ " ${dep} " ]]; then
                                new_dependencies+=("$dep")
                                log "      Found dependency: $dep"
                            fi
                        done <<< "$deps"
                    fi
                done
            done

            # Remove duplicates and update packages_to_download
            packages_to_download=()
            for dep in "${new_dependencies[@]}"; do
                if [[ ! " ${processed_packages[@]} " =~ " ${dep} " ]]; then
                    packages_to_download+=("$dep")
                fi
            done

            # Remove duplicates
            if [[ ${#packages_to_download[@]} -gt 0 ]]; then
                IFS=$'\n' packages_to_download=($(printf '%s\n' "${packages_to_download[@]}" | sort -u))
                log "    Found ${#packages_to_download[@]} new dependencies to resolve"
            fi
        done

        # Clean up temporary packages files
        rm -f "$TEMP_DIR"/Packages_*_$$.gz

        break  # Only process the first repository for dependency resolution
    done

    log "Dependency resolution completed. Total packages to download: ${#processed_packages[@]}"

    # Filter packages that need to be looked up
    local packages_to_lookup=()
    for package in "${processed_packages[@]}"; do
        # Skip if already downloaded (check only for non-Docker packages)
        case "$package" in
            docker-ce|docker-ce-cli|containerd.io)
                # Docker packages: always check for new versions
                packages_to_lookup+=("$package")
                ;;
            *)
                if [[ ! " ${downloaded_packages[@]} " =~ " ${package} " ]]; then
                    packages_to_lookup+=("$package")
                fi
                ;;
        esac
    done

    # Perform parallel package lookups with batch processing
    if [[ ${#packages_to_lookup[@]} -gt 0 ]]; then
        log "Resolving download URLs for ${#packages_to_lookup[@]} packages..."

        # Process packages in batches for better memory management
        local batch_size=$((PARALLEL_DOWNLOADS * 3))  # Process 3x parallel downloads at once
        local all_download_urls=()
        
        for ((i=0; i<${#packages_to_lookup[@]}; i+=batch_size)); do
            local batch=("${packages_to_lookup[@]:i:batch_size}")
            local batch_end=$((i + ${#batch[@]}))
            
            log "  Processing batch $((i/batch_size + 1)): packages $((i+1))-$batch_end of ${#packages_to_lookup[@]}"
            
            # Use parallel package lookups to collect URLs for this batch
            parallel_package_lookups "$download_dir" "${batch[@]}"

            # Accumulate URLs from this batch
            all_download_urls+=("${PARALLEL_LOOKUP_URLS[@]}")
        done
    else
        log "All packages already downloaded or no packages to lookup"
        local all_download_urls=()
    fi

    # Perform parallel downloads if we have URLs to download
    if [[ ${#all_download_urls[@]} -gt 0 ]]; then
        log "Starting parallel download of ${#all_download_urls[@]} files..."

        if parallel_download_files "$download_dir" "${all_download_urls[@]}"; then
            # Update downloaded packages based on successfully downloaded files
            for package in "${packages_to_lookup[@]}"; do
                # Check if any files for this package were downloaded successfully by checking downloaded URLs
                local package_downloaded=false
                
                for url in "${all_download_urls[@]}"; do
                    local deb_filename=$(basename "$url")
                    local local_path="$download_dir/$deb_filename"
                    
                    if [[ -f "$local_path" && -s "$local_path" ]]; then
                        # Check if this file belongs to the current package by filename pattern
                        if [[ "$deb_filename" == *"$package"* ]]; then
                            success "  Downloaded: $package ($deb_filename)"
                            package_downloaded=true
                        fi
                    fi
                done

                # Mark package as downloaded if any version was downloaded
                if [[ "$package_downloaded" == true ]]; then
                    if [[ ! " ${downloaded_packages[@]} " =~ " ${package} " ]]; then
                        downloaded_packages+=("$package")
                    fi
                fi
            done
        fi
    else
        log "All packages already downloaded or no valid URLs found"
    fi

    # Check for failed packages (only check originally requested packages)
    for package in "${PACKAGES[@]}"; do
        if [[ ! " ${downloaded_packages[@]} " =~ " ${package} " ]]; then
            failed_packages+=("$package")
        fi
    done

    # Clean up temporary packages files
    rm -f "$TEMP_DIR"/Packages_*_$$.gz

    log "Download completed:"
    log "  Downloaded: ${#downloaded_packages[@]} packages"
    log "  Failed: ${#failed_packages[@]} packages"

    if [[ ${#failed_packages[@]} -gt 0 ]]; then
        warning "Failed packages: ${failed_packages[*]}"
    fi

    # Check if we have any .deb files
    local deb_count=$(find "$download_dir" -name "*.deb" | wc -l)
    if [[ $deb_count -eq 0 ]]; then
        error "No packages were downloaded successfully"
    fi

    success "Successfully downloaded $deb_count .deb files"
}

# Create repository structure
create_repository() {
    log "Creating repository structure..."

    local download_dir="$TEMP_DIR/packages"
    local repo_dir="$MIRROR_DIR"

    # Remove existing repository
    if [[ -d "$repo_dir" ]]; then
        rm -rf "$repo_dir"
    fi

    # Create repository structure
    mkdir -p "$repo_dir/pool/main"
    mkdir -p "$repo_dir/dists/stable/main/binary-amd64"

    # Copy packages to pool
    if find "$download_dir" -name "*.deb" -type f | head -1 >/dev/null 2>&1; then
        cp "$download_dir"/*.deb "$repo_dir/pool/main/"
        success "Copied $(ls "$repo_dir/pool/main"/*.deb | wc -l) packages to repository"
    else
        error "No .deb files found to copy"
    fi

    # Generate Packages file
    cd "$repo_dir"
    dpkg-scanpackages --multiversion pool/main /dev/null > dists/stable/main/binary-amd64/Packages 2>/dev/null
    gzip -9c dists/stable/main/binary-amd64/Packages > dists/stable/main/binary-amd64/Packages.gz

    # Create Release file with proper checksums
    local packages_hash=$(sha256sum dists/stable/main/binary-amd64/Packages | cut -d' ' -f1)
    local packages_size=$(stat -c%s dists/stable/main/binary-amd64/Packages)
    local packages_gz_hash=$(sha256sum dists/stable/main/binary-amd64/Packages.gz | cut -d' ' -f1)
    local packages_gz_size=$(stat -c%s dists/stable/main/binary-amd64/Packages.gz)
    
    cat > dists/stable/Release << EOF
Origin: Local Mirror
Label: Local Mirror
Suite: stable
Codename: stable
Date: $(date -u "+%a, %d %b %Y %H:%M:%S UTC")
Architectures: amd64
Components: main
SHA256:
 $packages_hash $packages_size main/binary-amd64/Packages
 $packages_gz_hash $packages_gz_size main/binary-amd64/Packages.gz
EOF

    # Verify repository creation
    local pkg_count=$(cat dists/stable/main/binary-amd64/Packages | grep "^Package:" | wc -l)

    if [[ $pkg_count -gt 0 ]]; then
        success "Repository created with $pkg_count packages at: $repo_dir"
    else
        error "Repository creation failed - no packages in Packages file"
    fi
}

# Setup mirror directory
setup_mirror_directory() {
    log "Setting up mirror directory..."

    if [[ -d "$MIRROR_DIR" ]]; then
        log "Removing existing mirror directory..."
        rm -rf "$MIRROR_DIR"
    fi

    mkdir -p "$MIRROR_DIR"
    mkdir -p "$TEMP_DIR"

    success "Mirror directory created: $MIRROR_DIR"
}

# Cleanup
cleanup() {
    log "Cleaning up temporary files..."
    if [[ -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
    success "Cleanup completed"
}

# Build container image
build_container_image() {
    log "Building container image..."

    ls -la /tmp/repository

    # Check if docker/podman is available
    local container_cmd=""
    if command -v docker >/dev/null 2>&1; then
        container_cmd="docker"
    elif command -v podman >/dev/null 2>&1; then
        container_cmd="podman"
    else
        warning "Neither docker nor podman found. Skipping container image build."
        return
    fi

    # Generate image tag with current date
    local image_tag="quay.io/osism-mirror/ubuntu-noble:$(date +%Y%m%d)"
    local containerfile_path="/tmp/Containerfile"

    if [[ ! -f "$containerfile_path" ]]; then
        warning "Containerfile not found at: $containerfile_path. Skipping container image build."
        return
    fi

    log "Building container image: $image_tag"

    # Build container image with repository as build context
    if $container_cmd build \
        -t "$image_tag" \
        -f "$containerfile_path" \
        "$MIRROR_DIR"; then
        success "Container image built successfully: $image_tag"
        log "To push the image: $container_cmd push $image_tag"
    else
        warning "Failed to build container image"
    fi
}

# Main execution
main() {
    log "Starting Direct Package Mirror creation at $(date)"
    log "Script directory: $SCRIPT_DIR"
    log "Parallel downloads: $PARALLEL_DOWNLOADS concurrent connections"

    check_dependencies
    read_config
    setup_mirror_directory
    download_packages
    create_repository
    build_container_image
    cleanup

    success "Mirror creation completed successfully!"
    log "Mirror location: $MIRROR_DIR"
    log "$(date): Script execution finished"
}

# Trap for cleanup on exit
trap cleanup EXIT

# Run main function
main "$@"
