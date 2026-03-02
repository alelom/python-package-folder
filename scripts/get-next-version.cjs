#!/usr/bin/env node
/**
 * Get next version using semantic-release.
 * 
 * This script runs semantic-release in dry-run mode to determine the next version
 * for a package. It supports both subfolder builds (per-package tags) and main
 * package builds (repo-level tags).
 * 
 * Usage:
 *   node scripts/get-next-version.cjs <project_root> [subfolder_path] [package_name]
 * 
 * Args:
 *   - project_root: Root directory of the project (absolute or relative path)
 *   - subfolder_path: Optional. Path to subfolder relative to project_root (for Workflow 1)
 *   - package_name: Optional. Package name for subfolder builds (for per-package tags)
 * 
 * Output:
 *   - Version string (e.g., "1.2.3") if a release is determined
 *   - "none" if semantic-release determines no release is needed
 *   - Exits with non-zero code on error
 */

const path = require('path');
const fs = require('fs');

// Parse command line arguments
const args = process.argv.slice(2);
if (args.length < 1) {
  console.error('Error: project_root is required');
  console.error('Usage: node get-next-version.cjs <project_root> [subfolder_path] [package_name]');
  process.exit(1);
}

const projectRoot = path.resolve(args[0]);
const subfolderPath = args[1] || null;
const packageName = args[2] || null;

// Validate argument combination: both-or-neither for subfolder builds
if ((subfolderPath !== null && packageName === null) || (subfolderPath === null && packageName !== null)) {
  console.error('Error: subfolder_path and package_name must be provided together (both or neither).');
  console.error('Usage: node get-next-version.cjs <project_root> [subfolder_path] [package_name]');
  process.exit(1);
}

// Check if project root exists
if (!fs.existsSync(projectRoot)) {
  console.error(`Error: Project root does not exist: ${projectRoot}`);
  process.exit(1);
}

// Determine if this is a subfolder build
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

try {
  // Try to require semantic-release
  // First try resolving from project root (for devDependencies), then fall back to global
  let semanticRelease;
  try {
    const semanticReleasePath = require.resolve('semantic-release', { paths: [projectRoot] });
    semanticRelease = require(semanticReleasePath);
  } catch (resolveError) {
    try {
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

  // For subfolder builds, require semantic-release-commit-filter
  // (required only to verify it's installed; the plugin is used via options.plugins)
  // First try resolving from project root (for devDependencies), then fall back to global
  if (isSubfolderBuild) {
    try {
      const commitFilterPath = require.resolve('semantic-release-commit-filter', { paths: [projectRoot] });
      require(commitFilterPath);
    } catch (resolveError) {
      try {
        require('semantic-release-commit-filter');
      } catch (e) {
        console.error('Error: semantic-release-commit-filter is not installed.');
        console.error('Please install it with: npm install -g semantic-release-commit-filter');
        console.error('Or install it as a devDependency: npm install --save-dev semantic-release-commit-filter');
        process.exit(1);
      }
    }
  }

  // Configure semantic-release options
  const options = {
    dryRun: true,
    ci: false,
  };

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
