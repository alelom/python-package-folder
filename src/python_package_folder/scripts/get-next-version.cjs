#!/usr/bin/env node
/**
 * Get next version using semantic-release.
 * 
 * This script runs semantic-release in dry-run mode to determine the next version
 * for a package. It supports both subfolder builds (per-package tags) and main
 * package builds (repo-level tags).
 * 
 * Usage:
 *   node scripts/get-next-version.cjs <project_root> [subfolder_path] [package_name] [repository] [repository_url]
 * 
 * Args:
 *   - project_root: Root directory of the project (absolute or relative path)
 *   - subfolder_path: Optional. Path to subfolder relative to project_root (for Workflow 1)
 *   - package_name: Optional. Package name for subfolder builds (for per-package tags)
 *   - repository: Optional. Target repository ('pypi', 'testpypi', or 'azure')
 *   - repository_url: Optional. Repository URL (required for Azure Artifacts)
 * 
 * Output:
 *   - Version string (e.g., "1.2.3") if a release is determined
 *   - "none" if semantic-release determines no release is needed
 *   - Exits with non-zero code on error
 */

const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');
const { execSync } = require('child_process');

// Parse command line arguments
const args = process.argv.slice(2);
if (args.length < 1) {
  console.error('Error: project_root is required');
  console.error('Usage: node get-next-version.cjs <project_root> [subfolder_path] [package_name] [repository] [repository_url]');
  process.exit(1);
}

const projectRoot = path.resolve(args[0]);
const subfolderPath = args[1] && args[1] !== 'null' && args[1] !== '' ? args[1] : null;
const packageName = args[2] && args[2] !== 'null' && args[2] !== '' ? args[2] : null;
const repository = args[3] && args[3] !== 'null' && args[3] !== '' ? args[3] : null;
const repositoryUrl = args[4] && args[4] !== 'null' && args[4] !== '' ? args[4] : null;

// Validate argument combination
// - For subfolder builds: both subfolder_path and package_name are required
// - For main package builds: package_name can be provided alone (for registry queries)
if (subfolderPath !== null && packageName === null) {
  console.error('Error: package_name is required when subfolder_path is provided.');
  console.error('Usage: node get-next-version.cjs <project_root> [subfolder_path] [package_name] [repository] [repository_url]');
  process.exit(1);
}
// Note: package_name can be provided without subfolder_path for main package registry queries

// Check if project root exists
if (!fs.existsSync(projectRoot)) {
  console.error(`Error: Project root does not exist: ${projectRoot}`);
  process.exit(1);
}

// Determine if this is a subfolder build
// A subfolder build requires both subfolder_path and package_name
// package_name alone (without subfolder_path) indicates a main package build with registry query
const isSubfolderBuild = subfolderPath !== null && packageName !== null;
const workingDir = isSubfolderBuild 
  ? path.resolve(projectRoot, subfolderPath)
  : projectRoot;

// Check if working directory exists
if (!fs.existsSync(workingDir)) {
  console.error(`Error: Working directory does not exist: ${workingDir}`);
  process.exit(1);
}

// For subfolder builds, ensure package.json exists with correct name
let tempPackageJson = null;
let backupCreatedByScript = false;
let fileCreatedByScript = false;
let originalPackageJsonContent = null; // Track original content for restoration
if (isSubfolderBuild) {
  const packageJsonPath = path.join(workingDir, 'package.json');
  const hadPackageJson = fs.existsSync(packageJsonPath);
  
  if (!hadPackageJson) {
    // Create temporary package.json for semantic-release-commit-filter
    const packageJsonContent = JSON.stringify({
      name: packageName,
      version: '0.0.0'
    }, null, 2);
    fs.writeFileSync(packageJsonPath, packageJsonContent, 'utf8');
    tempPackageJson = packageJsonPath;
    fileCreatedByScript = true;
  } else {
    // Read existing package.json and ensure name matches
    try {
      const existing = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
      const backup = packageJsonPath + '.backup';
      const backupExists = fs.existsSync(backup);
      
      // Store original content before any modifications
      originalPackageJsonContent = fs.readFileSync(packageJsonPath, 'utf8');
      
      if (existing.name !== packageName) {
        // Need to modify the name
        // Check if backup is stale (from a previous crashed run)
        // A backup is stale if it contains the same name we're trying to set
        let isStaleBackup = false;
        if (backupExists) {
          try {
            const backupContent = JSON.parse(fs.readFileSync(backup, 'utf8'));
            // If backup has the name we're trying to set, it's stale from a previous run
            if (backupContent.name === packageName) {
              isStaleBackup = true;
            }
          } catch (e) {
            // If we can't read the backup, treat it as potentially stale
            isStaleBackup = true;
          }
        }
        
        // If backup is stale, restore from it first, then create a fresh backup
        if (isStaleBackup) {
          try {
            fs.copyFileSync(backup, packageJsonPath);
            // Re-read after restoration and update original content
            originalPackageJsonContent = fs.readFileSync(packageJsonPath, 'utf8');
            const restored = JSON.parse(originalPackageJsonContent);
            // Now create a fresh backup of the restored original
            fs.copyFileSync(packageJsonPath, backup);
            backupCreatedByScript = true;
            // Update the restored content with the new name
            restored.name = packageName;
            fs.writeFileSync(packageJsonPath, JSON.stringify(restored, null, 2), 'utf8');
          } catch (e) {
            // If restoration fails, create a new backup of current state
            fs.copyFileSync(packageJsonPath, backup);
            backupCreatedByScript = true;
            existing.name = packageName;
            fs.writeFileSync(packageJsonPath, JSON.stringify(existing, null, 2), 'utf8');
          }
        } else {
          // Backup doesn't exist or is valid (preserves user's original)
          // If backup exists, it's user's backup - we'll restore from originalPackageJsonContent
          // If backup doesn't exist, create one
          if (!backupExists) {
            fs.copyFileSync(packageJsonPath, backup);
            backupCreatedByScript = true;
          }
          // Modify the file
          existing.name = packageName;
          fs.writeFileSync(packageJsonPath, JSON.stringify(existing, null, 2), 'utf8');
        }
        tempPackageJson = packageJsonPath;
      } else if (backupExists) {
        // Name already matches, but check if backup is stale
        // If backup has the same name, it's from a previous crashed run
        try {
          const backupContent = JSON.parse(fs.readFileSync(backup, 'utf8'));
          if (backupContent.name === packageName) {
            // Stale backup from previous run - restore it
            fs.copyFileSync(backup, packageJsonPath);
            // Update original content after restoration
            originalPackageJsonContent = fs.readFileSync(packageJsonPath, 'utf8');
            // Remove stale backup since we've restored
            fs.unlinkSync(backup);
            // Re-check if we need to modify after restoration
            const restored = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
            if (restored.name !== packageName) {
              // After restoration, name doesn't match - need to modify
              fs.copyFileSync(packageJsonPath, backup);
              backupCreatedByScript = true;
              restored.name = packageName;
              fs.writeFileSync(packageJsonPath, JSON.stringify(restored, null, 2), 'utf8');
              tempPackageJson = packageJsonPath;
            }
          }
        } catch (e) {
          // If we can't read backup, leave it as-is (might be user's backup)
        }
      }
    } catch (e) {
      console.error(`Error reading package.json: ${e.message}`);
      process.exit(1);
    }
  }
}

/**
 * Query PyPI or TestPyPI JSON API for the latest version of a package.
 * @param {string} packageName - Package name to query
 * @param {string} registry - 'pypi' or 'testpypi'
 * @returns {Promise<string|null>} Latest version string or null if not found
 */
async function queryPyPIVersion(packageName, registry) {
  const baseUrl = registry === 'testpypi' 
    ? 'https://test.pypi.org'
    : 'https://pypi.org';
  const url = `${baseUrl}/pypi/${packageName}/json`;
  
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      
      res.on('data', (chunk) => {
        data += chunk;
      });
      
      res.on('end', () => {
        if (res.statusCode === 404) {
          // Package doesn't exist yet (first release)
          resolve(null);
        } else if (res.statusCode === 200) {
          try {
            const json = JSON.parse(data);
            // Get latest version from info.version or releases
            const version = json.info?.version || Object.keys(json.releases || {}).pop() || null;
            resolve(version);
          } catch (e) {
            reject(new Error(`Failed to parse PyPI response: ${e.message}`));
          }
        } else {
          reject(new Error(`PyPI API returned status ${res.statusCode}`));
        }
      });
    }).on('error', (err) => {
      reject(err);
    });
  });
}

/**
 * Query Azure Artifacts for the latest version of a package.
 * Azure Artifacts uses a simple index format (HTML) which is more complex to parse.
 * For now, we'll attempt to query but fall back gracefully if it fails.
 * @param {string} packageName - Package name to query
 * @param {string} repositoryUrl - Azure Artifacts repository URL
 * @returns {Promise<string|null>} Latest version string or null if not found/unsupported
 */
async function queryAzureArtifactsVersion(packageName, repositoryUrl) {
  // Convert upload URL to simple index URL
  // Upload: https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/upload
  // Simple: https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/simple/{package}/
  let simpleIndexUrl;
  try {
    const url = new URL(repositoryUrl);
    if (url.pathname.endsWith('/upload')) {
      simpleIndexUrl = repositoryUrl.replace('/upload', `/simple/${packageName}/`);
    } else {
      // Try to construct from common patterns
      simpleIndexUrl = repositoryUrl.replace(/\/upload$/, `/simple/${packageName}/`);
    }
  } catch (e) {
    // Invalid URL format, return null to fall back to git tags
    return null;
  }
  
  return new Promise((resolve) => {
    // Azure Artifacts may require authentication and returns HTML
    // For now, we'll attempt the request but gracefully fall back if it fails
    // This is a limitation - Azure Artifacts API is more complex than PyPI
    const url = new URL(simpleIndexUrl);
    const client = url.protocol === 'https:' ? https : http;
    
    const req = client.get(simpleIndexUrl, (res) => {
      // Azure Artifacts simple index returns HTML, not JSON
      // Parsing HTML is complex and may require authentication
      // For now, we'll return null to fall back to git tags
      // This can be enhanced later with proper HTML parsing or API endpoint discovery
      resolve(null);
    });
    
    req.on('error', () => {
      // Network error or authentication required - fall back to git tags
      resolve(null);
    });
    
    req.setTimeout(5000, () => {
      req.destroy();
      resolve(null);
    });
  });
}

/**
 * Query the package registry for the latest published version.
 * @param {string} packageName - Package name to query
 * @param {string|null} repository - Repository type ('pypi', 'testpypi', 'azure', or null)
 * @param {string|null} repositoryUrl - Repository URL (for Azure)
 * @returns {Promise<string|null>} Latest version or null if not found/unsupported
 */
async function queryRegistryVersion(packageName, repository, repositoryUrl) {
  if (!repository || !packageName) {
    return null;
  }
  
  try {
    if (repository === 'pypi' || repository === 'testpypi') {
      return await queryPyPIVersion(packageName, repository);
    } else if (repository === 'azure') {
      if (!repositoryUrl) {
        return null;
      }
      return await queryAzureArtifactsVersion(packageName, repositoryUrl);
    }
  } catch (error) {
    // Log error but don't fail - fall back to git tags
    console.error(`Warning: Failed to query ${repository} for latest version: ${error.message}`);
    console.error('Falling back to git tags for version detection.');
  }
  
  return null;
}

/**
 * Get global npm prefix for module resolution.
 * This helps find globally installed npm packages.
 * @returns {string|null} Path to global node_modules or null if not found
 */
function getGlobalNpmPrefix() {
  try {
    // Get npm's global prefix (where global packages are installed)
    const prefix = execSync('npm config get prefix', { encoding: 'utf8' }).trim();
    // Global node_modules is typically at <prefix>/lib/node_modules
    const globalNodeModules = path.join(prefix, 'lib', 'node_modules');
    if (fs.existsSync(globalNodeModules)) {
      return globalNodeModules;
    }
    // Alternative location on some systems
    const altGlobalNodeModules = path.join(prefix, 'node_modules');
    if (fs.existsSync(altGlobalNodeModules)) {
      return altGlobalNodeModules;
    }
    return null;
  } catch (e) {
    // If npm config fails, try to find it via NODE_PATH or common locations
    return null;
  }
}

// Main execution
(async () => {
  try {
    // Get global npm path for module resolution
    const globalNpmPath = getGlobalNpmPrefix();
    const resolvePaths = [projectRoot];
    if (globalNpmPath) {
      resolvePaths.push(globalNpmPath);
    }
    
    // Try to require semantic-release
    // First try resolving from project root (for devDependencies), then try global, then fall back to default
    let semanticRelease;
    try {
      const semanticReleasePath = require.resolve('semantic-release', { paths: resolvePaths });
      semanticRelease = require(semanticReleasePath);
    } catch (resolveError) {
      try {
        // Try with just global path
        if (globalNpmPath) {
          const semanticReleasePath = require.resolve('semantic-release', { paths: [globalNpmPath] });
          semanticRelease = require(semanticReleasePath);
        } else {
          throw resolveError;
        }
      } catch (globalError) {
        try {
          // Final fallback: default require (should work if in NODE_PATH or default locations)
          semanticRelease = require('semantic-release');
        } catch (e) {
          console.error('Error: semantic-release is not installed.');
          console.error('Please install it with: npm install -g semantic-release');
          console.error('Or install it as a devDependency: npm install --save-dev semantic-release');
          if (isSubfolderBuild) {
            console.error('For subfolder builds, also install: npm install -g semantic-release-commit-filter');
            console.error('Or as devDependency: npm install --save-dev semantic-release-commit-filter');
          }
          process.exit(1);
        }
      }
    }

    // For subfolder builds, require semantic-release-commit-filter
    // (required only to verify it's installed; the plugin is used via options.plugins)
    if (isSubfolderBuild) {
      try {
        const commitFilterPath = require.resolve('semantic-release-commit-filter', { paths: resolvePaths });
        require(commitFilterPath);
      } catch (resolveError) {
        try {
          // Try with just global path
          if (globalNpmPath) {
            const commitFilterPath = require.resolve('semantic-release-commit-filter', { paths: [globalNpmPath] });
            require(commitFilterPath);
          } else {
            throw resolveError;
          }
        } catch (globalError) {
          try {
            // Final fallback: default require
            require('semantic-release-commit-filter');
          } catch (e) {
            console.error('Error: semantic-release-commit-filter is not installed.');
            console.error('Please install it with: npm install -g semantic-release-commit-filter');
            console.error('Or install it as a devDependency: npm install --save-dev semantic-release-commit-filter');
            process.exit(1);
          }
        }
      }
    }

  // Query registry for latest version if repository info is provided
  let registryVersion = null;
  if (repository && packageName) {
    try {
      registryVersion = await queryRegistryVersion(packageName, repository, repositoryUrl);
      if (registryVersion) {
        console.error(`Found latest version on ${repository}: ${registryVersion}`);
      } else {
        console.error(`Package not found on ${repository} or query failed, using git tags as fallback`);
      }
    } catch (error) {
      console.error(`Warning: Registry query failed: ${error.message}`);
      console.error('Falling back to git tags for version detection.');
    }
  }

  // Configure semantic-release options
  const options = {
    dryRun: true,
    ci: false,
  };
  
  // If we have a registry version, we can use it to set lastRelease in semantic-release context
  // This ensures semantic-release uses the registry version as baseline instead of git tags
  if (registryVersion) {
    // Set lastRelease in options to use registry version as baseline
    // This tells semantic-release to analyze commits since this version
    options.lastRelease = {
      version: registryVersion,
      gitTag: isSubfolderBuild 
        ? `${packageName}-v${registryVersion}`
        : `v${registryVersion}`,
      gitHead: null, // We don't know the commit, but semantic-release will find it
    };
  }

  // For subfolder builds, configure commit filter and per-package tags
  if (isSubfolderBuild) {
    // Get relative path from project root to subfolder for commit filtering
    const relPath = path.relative(projectRoot, workingDir).replace(/\\/g, '/');
    
    options.plugins = [
      ['@semantic-release/commit-analyzer', {
        preset: 'angular',
      }],
      ['semantic-release-commit-filter', {
        cwd: workingDir,
        path: relPath,
      }],
      ['@semantic-release/release-notes-generator', {
        preset: 'angular',
      }],
    ];
    
    // Use per-package tag format: {package-name}-v{version}
    options.tagFormat = `${packageName}-v\${version}`;
  } else {
    // Main package: use default tag format v{version}
    options.plugins = [
      ['@semantic-release/commit-analyzer', {
        preset: 'angular',
      }],
      ['@semantic-release/release-notes-generator', {
        preset: 'angular',
      }],
    ];
  }

  // Run semantic-release (returns a promise)
  semanticRelease(options, {
    cwd: workingDir,
    env: {
      ...process.env,
      // Ensure git commands run from project root for subfolder builds
      GIT_DIR: path.join(projectRoot, '.git'),
      GIT_WORK_TREE: projectRoot,
    },
  }).then((result) => {
    // Clean up temporary package.json if we created or modified it
    if (tempPackageJson && fs.existsSync(tempPackageJson)) {
      const backup = tempPackageJson + '.backup';
      if (backupCreatedByScript && fs.existsSync(backup)) {
        // Restore original (only if we created the backup)
        fs.copyFileSync(backup, tempPackageJson);
        fs.unlinkSync(backup);
      } else if (fileCreatedByScript) {
        // Remove temporary file (only if we created it, not if it existed before)
        fs.unlinkSync(tempPackageJson);
      } else if (originalPackageJsonContent !== null) {
        // We modified an existing file but didn't create a backup (user's backup exists)
        // Restore from the original content we stored, but don't delete user's backup
        fs.writeFileSync(tempPackageJson, originalPackageJsonContent, 'utf8');
      }
    }

    // Output result
    if (result && result.nextRelease && result.nextRelease.version) {
      console.log(result.nextRelease.version);
      process.exit(0);
    } else {
      console.log('none');
      process.exit(0);
    }
  }).catch((error) => {
    // Clean up temporary package.json on error
    if (tempPackageJson && fs.existsSync(tempPackageJson)) {
      const backup = tempPackageJson + '.backup';
      if (backupCreatedByScript && fs.existsSync(backup)) {
        try {
          // Restore original (only if we created the backup)
          fs.copyFileSync(backup, tempPackageJson);
          fs.unlinkSync(backup);
        } catch (e) {
          // Ignore cleanup errors
        }
      } else if (fileCreatedByScript) {
        try {
          // Remove temporary file (only if we created it, not if it existed before)
          fs.unlinkSync(tempPackageJson);
        } catch (e) {
          // Ignore cleanup errors
        }
      } else if (originalPackageJsonContent !== null) {
        // We modified an existing file but didn't create a backup (user's backup exists)
        // Restore from the original content we stored, but don't delete user's backup
        try {
          fs.writeFileSync(tempPackageJson, originalPackageJsonContent, 'utf8');
        } catch (e) {
          // Ignore cleanup errors
        }
      }
    }

    // Check if it's a "no release" case (common, not an error)
    if (error.message && (
      error.message.includes('no release') ||
      error.message.includes('No release') ||
      error.code === 'ENOCHANGE'
    )) {
      console.log('none');
      process.exit(0);
    }

    // Other errors
    console.error(`Error running semantic-release: ${error.message}`);
    if (error.stack) {
      console.error(error.stack);
    }
    process.exit(1);
  });
  } catch (error) {
    // Clean up temporary package.json on error
    if (tempPackageJson && fs.existsSync(tempPackageJson)) {
      const backup = tempPackageJson + '.backup';
      if (backupCreatedByScript && fs.existsSync(backup)) {
        try {
          // Restore original (only if we created the backup)
          fs.copyFileSync(backup, tempPackageJson);
          fs.unlinkSync(backup);
        } catch (e) {
          // Ignore cleanup errors
        }
      } else if (fileCreatedByScript) {
        try {
          // Remove temporary file (only if we created it, not if it existed before)
          fs.unlinkSync(tempPackageJson);
        } catch (e) {
          // Ignore cleanup errors
        }
      } else if (originalPackageJsonContent !== null) {
        // We modified an existing file but didn't create a backup (user's backup exists)
        // Restore from the original content we stored, but don't delete user's backup
        try {
          fs.writeFileSync(tempPackageJson, originalPackageJsonContent, 'utf8');
        } catch (e) {
          // Ignore cleanup errors
        }
      }
    }

    // Check if it's a "no release" case (common, not an error)
    if (error.message && (
      error.message.includes('no release') ||
      error.message.includes('No release') ||
      error.code === 'ENOCHANGE'
    )) {
      console.log('none');
      process.exit(0);
    }

    // Other errors
    console.error(`Error: ${error.message}`);
    if (error.stack) {
      console.error(error.stack);
    }
    process.exit(1);
  }
})();
