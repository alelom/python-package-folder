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
const { execSync } = require('child_process');

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
  } else {
    // Read existing package.json and ensure name matches
    try {
      const existing = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
      if (existing.name !== packageName) {
        // Backup original and update name
        // Only create backup if one doesn't exist (preserve original from previous runs)
        const backup = packageJsonPath + '.backup';
        if (!fs.existsSync(backup)) {
          fs.copyFileSync(packageJsonPath, backup);
        }
        existing.name = packageName;
        fs.writeFileSync(packageJsonPath, JSON.stringify(existing, null, 2), 'utf8');
        tempPackageJson = packageJsonPath;
      }
    } catch (e) {
      console.error(`Error reading package.json: ${e.message}`);
      process.exit(1);
    }
  }
}

try {
  // Try to require semantic-release
  let semanticRelease;
  try {
    semanticRelease = require('semantic-release');
  } catch (e) {
    console.error('Error: semantic-release is not installed.');
    console.error('Please install it with: npm install -g semantic-release');
    if (isSubfolderBuild) {
      console.error('For subfolder builds, also install: npm install -g semantic-release-commit-filter');
    }
    process.exit(1);
  }

  // For subfolder builds, require semantic-release-commit-filter
  let commitFilter;
  if (isSubfolderBuild) {
    try {
      commitFilter = require('semantic-release-commit-filter');
    } catch (e) {
      console.error('Error: semantic-release-commit-filter is not installed.');
      console.error('Please install it with: npm install -g semantic-release-commit-filter');
      process.exit(1);
    }
  }

  // Configure semantic-release options
  const options = {
    dryRun: true,
    ci: false,
    branches: ['main', 'master'], // Default branches, can be overridden by config
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
    // Clean up temporary package.json if we created it
    if (tempPackageJson && fs.existsSync(tempPackageJson)) {
      const backup = tempPackageJson + '.backup';
      if (fs.existsSync(backup)) {
        // Restore original
        fs.copyFileSync(backup, tempPackageJson);
        fs.unlinkSync(backup);
      } else {
        // Remove temporary file
        fs.unlinkSync(tempPackageJson);
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
      if (fs.existsSync(backup)) {
        try {
          fs.copyFileSync(backup, tempPackageJson);
          fs.unlinkSync(backup);
        } catch (e) {
          // Ignore cleanup errors
        }
      } else {
        try {
          fs.unlinkSync(tempPackageJson);
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
    if (fs.existsSync(backup)) {
      try {
        fs.copyFileSync(backup, tempPackageJson);
        fs.unlinkSync(backup);
      } catch (e) {
        // Ignore cleanup errors
      }
    } else {
      try {
        fs.unlinkSync(tempPackageJson);
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
