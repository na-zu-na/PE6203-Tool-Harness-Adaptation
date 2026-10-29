#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import fs from "fs/promises";
import path from "path";
import os from 'os';
import { z } from "zod";
import { diffLines, createTwoFilesPatch } from 'diff';
import { minimatch } from 'minimatch';

// Utility functions
function normalizePath(p) {
    return path.normalize(p);
}

function expandHome(filepath) {
    if (filepath.startsWith('~/') || filepath === '~') {
        return path.join(os.homedir(), filepath.slice(1));
    }
    return filepath;
}

// Path resolution - handles expanding home directory (~), resolving relative paths, and checking symlinks
async function resolvePath(requestedPath) {
    try {
        const expandedPath = expandHome(requestedPath);
        // 상대 경로인 경우 현재 작업 디렉토리(pwd)를 기준으로 처리
        const absolute = path.isAbsolute(expandedPath)
            ? path.resolve(expandedPath)
            : path.resolve(process.cwd(), expandedPath);

        const normalizedRequested = normalizePath(absolute);

        // Handle symlinks by returning their real path
        try {
            const realPath = await fs.realpath(absolute);
            return realPath;
        } catch (error) {
            // For new files that don't exist yet, verify parent directory
            const parentDir = path.dirname(absolute);
            try {
                await fs.realpath(parentDir);
                return absolute;
            } catch (parentError) {
                throw new Error(`경로 오류: 부모 디렉토리가 존재하지 않습니다 - ${parentDir}`);
            }
        }
    } catch (error) {
        // 더 명확한 오류 메시지를 위해 오류 유형 구분
        if (error.code === 'EACCES') {
            throw new Error(`접근 거부: 권한이 없습니다 - ${requestedPath}`);
        } else if (error.code === 'ENOENT') {
            throw new Error(`경로 오류: 파일 또는 디렉토리가 존재하지 않습니다 - ${requestedPath}`);
        } else {
            throw error; // 다른 오류는 그대로 전달
        }
    }
}

// Schema definitions
const ReadFileArgsSchema = z.object({
    path: z.string(),
    encoding: z.string().optional().default('utf-8').describe("File encoding (default: utf-8)")
});

const ReadBinaryFileArgsSchema = z.object({
    path: z.string()
});

const ReadMultipleFilesArgsSchema = z.object({
    paths: z.array(z.string()),
    encoding: z.string().optional().default('utf-8').describe("File encoding (default: utf-8)")
});

const WriteFileArgsSchema = z.object({
    path: z.string(),
    content: z.string(),
    createDirectories: z.boolean().optional().default(false).describe("Create parent directories if they don't exist")
});

const EditOperation = z.object({
    oldText: z.string().describe('Text to search for - must match exactly'),
    newText: z.string().describe('Text to replace with')
});

const EditFileArgsSchema = z.object({
    path: z.string(),
    edits: z.array(EditOperation),
    dryRun: z.boolean().default(false).describe('Preview changes using git-style diff format')
});

const CreateDirectoryArgsSchema = z.object({
    path: z.string(),
});

const ListDirectoryArgsSchema = z.object({
    path: z.string(),
    showHidden: z.boolean().optional().default(false).describe("Show hidden files starting with .")
});

const DirectoryTreeArgsSchema = z.object({
    path: z.string(),
    maxDepth: z.number().optional().default(10).describe("Maximum depth to traverse"),
    includeFiles: z.boolean().optional().default(true).describe("Include files in the output"),
    showHidden: z.boolean().optional().default(false).describe("Show hidden files starting with .")
});

const MoveFileArgsSchema = z.object({
    source: z.string(),
    destination: z.string(),
    overwrite: z.boolean().optional().default(false).describe("Overwrite destination if it exists")
});

const SearchFilesArgsSchema = z.object({
    path: z.string(),
    pattern: z.string(),
    maxResults: z.number().optional().default(1000).describe("Maximum number of results to return"),
    maxDepth: z.number().optional().default(20).describe("Maximum depth to search"),
    excludePatterns: z.array(z.string()).optional().default([]).describe("Patterns to exclude from search"),
    searchContents: z.boolean().optional().default(false).describe("Search file contents instead of just names")
});

const GetFileInfoArgsSchema = z.object({
    path: z.string(),
});

// Server setup
const server = new McpServer({
    name: "filesystem-server",
    version: "1.0.0"
});

// Tool implementations
async function getFileStats(filePath) {
    try {
        const stats = await fs.stat(filePath);
        return {
            size: stats.size,
            created: stats.birthtime,
            modified: stats.mtime,
            accessed: stats.atime,
            isDirectory: stats.isDirectory(),
            isFile: stats.isFile(),
            isSymbolicLink: stats.isSymbolicLink(),
            permissions: stats.mode.toString(8).slice(-3),
        };
    } catch (error) {
        if (error.code === 'ENOENT') {
            throw new Error(`파일을 찾을 수 없습니다: ${filePath}`);
        } else if (error.code === 'EACCES') {
            throw new Error(`접근 권한이 없습니다: ${filePath}`);
        } else {
            throw error;
        }
    }
}

async function searchFiles(
    rootPath,
    pattern,
    maxResults = 1000,
    maxDepth = 20,
    excludePatterns = [],
    searchContents = false
) {
    const results = [];
    let currentDepth = 0;

    async function search(currentPath, depth) {
        // 최대 깊이 확인
        if (depth > maxDepth) return;
        if (results.length >= maxResults) return;

        let entries;
        try {
            entries = await fs.readdir(currentPath, { withFileTypes: true });
        } catch (error) {
            // 접근할 수 없는 디렉토리는 건너뜁니다
            return;
        }

        for (const entry of entries) {
            // 최대 결과 수 확인
            if (results.length >= maxResults) return;

            const fullPath = path.join(currentPath, entry.name);

            try {
                // Check if path matches any exclude pattern
                const relativePath = path.relative(rootPath, fullPath);
                const shouldExclude = excludePatterns.some(pattern => {
                    const globPattern = pattern.includes('*') ? pattern : `**/${pattern}/**`;
                    return minimatch(relativePath, globPattern, { dot: true });
                });

                if (shouldExclude) {
                    continue;
                }

                // 파일 이름으로 검색
                if (entry.name.toLowerCase().includes(pattern.toLowerCase())) {
                    results.push(fullPath);
                }

                // 파일 내용 검색 (옵션)
                if (searchContents && entry.isFile()) {
                    try {
                        const content = await fs.readFile(fullPath, 'utf-8');
                        if (content.toLowerCase().includes(pattern.toLowerCase())) {
                            if (!results.includes(fullPath)) {
                                results.push(fullPath);
                            }
                        }
                    } catch (error) {
                        // 읽을 수 없는 파일은 건너뜁니다
                    }
                }

                // 디렉토리인 경우 재귀 검색
                if (entry.isDirectory()) {
                    await search(fullPath, depth + 1);
                }
            } catch (error) {
                // 접근할 수 없는 파일/디렉토리는 건너뜁니다
                continue;
            }
        }
    }

    await search(rootPath, currentDepth);
    return results;
}

// File editing and diffing utilities
function normalizeLineEndings(text) {
    return text.replace(/\r\n/g, '\n');
}

function createUnifiedDiff(originalContent, newContent, filepath = 'file') {
    // Ensure consistent line endings for diff
    const normalizedOriginal = normalizeLineEndings(originalContent);
    const normalizedNew = normalizeLineEndings(newContent);

    return createTwoFilesPatch(
        filepath,
        filepath,
        normalizedOriginal,
        normalizedNew,
        'original',
        'modified'
    );
}

async function applyFileEdits(
    filePath,
    edits,
    dryRun = false
) {
    // Read file content and normalize line endings
    const content = normalizeLineEndings(await fs.readFile(filePath, 'utf-8'));

    // Apply edits sequentially
    let modifiedContent = content;
    for (const edit of edits) {
        const normalizedOld = normalizeLineEndings(edit.oldText);
        const normalizedNew = normalizeLineEndings(edit.newText);

        // If exact match exists, use it
        if (modifiedContent.includes(normalizedOld)) {
            modifiedContent = modifiedContent.replace(normalizedOld, normalizedNew);
            continue;
        }

        // Otherwise, try line-by-line matching with flexibility for whitespace
        const oldLines = normalizedOld.split('\n');
        const contentLines = modifiedContent.split('\n');
        let matchFound = false;

        for (let i = 0; i <= contentLines.length - oldLines.length; i++) {
            const potentialMatch = contentLines.slice(i, i + oldLines.length);

            // Compare lines with normalized whitespace
            const isMatch = oldLines.every((oldLine, j) => {
                const contentLine = potentialMatch[j];
                return oldLine.trim() === contentLine.trim();
            });

            if (isMatch) {
                // Preserve original indentation of first line
                const originalIndent = contentLines[i].match(/^\s*/)?.[0] || '';
                const newLines = normalizedNew.split('\n').map((line, j) => {
                    if (j === 0) return originalIndent + line.trimStart();
                    // For subsequent lines, try to preserve relative indentation
                    const oldIndent = oldLines[j]?.match(/^\s*/)?.[0] || '';
                    const newIndent = line.match(/^\s*/)?.[0] || '';
                    if (oldIndent && newIndent) {
                        const relativeIndent = newIndent.length - oldIndent.length;
                        return originalIndent + ' '.repeat(Math.max(0, relativeIndent)) + line.trimStart();
                    }
                    return line;
                });

                contentLines.splice(i, oldLines.length, ...newLines);
                modifiedContent = contentLines.join('\n');
                matchFound = true;
                break;
            }
        }

        if (!matchFound) {
            throw new Error(`수정할 텍스트를 찾을 수 없습니다:\n${edit.oldText}`);
        }
    }

    // Create unified diff
    const diff = createUnifiedDiff(content, modifiedContent, filePath);

    // Format diff with appropriate number of backticks
    let numBackticks = 3;
    while (diff.includes('`'.repeat(numBackticks))) {
        numBackticks++;
    }
    const formattedDiff = `${'`'.repeat(numBackticks)}diff\n${diff}${'`'.repeat(numBackticks)}\n\n`;

    if (!dryRun) {
        await fs.writeFile(filePath, modifiedContent, 'utf-8');
    }

    return formattedDiff;
}

// Tool handlers
server.tool(
    "read_file",
    "Read the complete contents of a file from the file system. Handles various text encodings and provides detailed error messages if the file cannot be read.",
    {
        path: z.string().describe("The path to the file"),
        encoding: z.string().optional().default('utf-8').describe("File encoding (default: utf-8)")
    },
    async ({ path: filePath, encoding }) => {
        try {
            const resolvedPath = await resolvePath(filePath);
            const content = await fs.readFile(resolvedPath, encoding);
            return {
                content: [{ type: "text", text: content }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "read_binary_file",
    "Read a binary file and return its contents as base64 encoded string.",
    {
        path: z.string().describe("The path to the binary file")
    },
    async ({ path: filePath }) => {
        try {
            const resolvedPath = await resolvePath(filePath);
            const content = await fs.readFile(resolvedPath);
            return {
                content: [{
                    type: "text",
                    text: `Base64 encoded file content (${content.length} bytes):\n${content.toString('base64')}`
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "read_multiple_files",
    "Read the contents of multiple files simultaneously. This is more efficient than reading files one by one when you need to analyze or compare multiple files.",
    {
        paths: z.array(z.string()).describe("Array of file paths to read"),
        encoding: z.string().optional().default('utf-8').describe("File encoding (default: utf-8)")
    },
    async ({ paths, encoding }) => {
        try {
            const results = await Promise.all(
                paths.map(async (filePath) => {
                    try {
                        const resolvedPath = await resolvePath(filePath);
                        const content = await fs.readFile(resolvedPath, encoding);
                        return `${filePath}:\n${content}\n`;
                    } catch (error) {
                        return `${filePath}: Error - ${error.message}`;
                    }
                })
            );
            return {
                content: [{ type: "text", text: results.join("\n---\n") }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "write_file",
    "Create a new file or completely overwrite an existing file with new content. Use with caution as it will overwrite existing files without warning.",
    {
        path: z.string().describe("The path to the file"),
        content: z.string().describe("The content to write to the file"),
        createDirectories: z.boolean().optional().default(false).describe("Create parent directories if they don't exist")
    },
    async ({ path: filePath, content, createDirectories }) => {
        try {
            const resolvedPath = await resolvePath(filePath);

            // 필요한 경우 부모 디렉토리 생성
            if (createDirectories) {
                const dirPath = path.dirname(resolvedPath);
                await fs.mkdir(dirPath, { recursive: true });
            }

            await fs.writeFile(resolvedPath, content, "utf-8");
            return {
                content: [{ type: "text", text: `Successfully wrote to ${filePath}` }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "edit_file",
    "Make line-based edits to a text file. Each edit replaces exact line sequences with new content. Returns a git-style diff showing the changes made.",
    {
        path: z.string().describe("The path to the file"),
        edits: z.array(z.object({
            oldText: z.string().describe("Text to search for - must match exactly"),
            newText: z.string().describe("Text to replace with")
        })).describe("Array of edit operations"),
        dryRun: z.boolean().default(false).describe("Preview changes using git-style diff format")
    },
    async ({ path: filePath, edits, dryRun }) => {
        try {
            const resolvedPath = await resolvePath(filePath);
            const result = await applyFileEdits(resolvedPath, edits, dryRun);
            return {
                content: [{
                    type: "text",
                    text: `${dryRun ? "Preview of changes (dry run):" : "Applied changes:"}\n${result}`
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "create_directory",
    "Create a new directory or ensure a directory exists. Can create multiple nested directories in one operation.",
    {
        path: z.string().describe("The path to the directory")
    },
    async ({ path: dirPath }) => {
        try {
            const resolvedPath = await resolvePath(dirPath);
            await fs.mkdir(resolvedPath, { recursive: true });
            return {
                content: [{ type: "text", text: `Successfully created directory ${dirPath}` }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "list_directory",
    "Get a detailed listing of all files and directories in a specified path. Results clearly distinguish between files and directories with [FILE] and [DIR] prefixes.",
    {
        path: z.string().describe("The path to the directory"),
        showHidden: z.boolean().optional().default(false).describe("Show hidden files starting with .")
    },
    async ({ path: dirPath, showHidden }) => {
        try {
            const resolvedPath = await resolvePath(dirPath);
            const entries = await fs.readdir(resolvedPath, { withFileTypes: true });

            // 숨김 파일 필터링
            const filteredEntries = showHidden
                ? entries
                : entries.filter(entry => !entry.name.startsWith('.'));

            // 디렉토리 먼저, 그 다음 파일 순으로 정렬
            const sortedEntries = filteredEntries.sort((a, b) => {
                if (a.isDirectory() && !b.isDirectory()) return -1;
                if (!a.isDirectory() && b.isDirectory()) return 1;
                return a.name.localeCompare(b.name);
            });

            const formatted = sortedEntries
                .map((entry) => {
                    let prefix = entry.isDirectory() ? "[DIR]" : "[FILE]";
                    if (entry.isSymbolicLink()) prefix = "[LINK]";
                    return `${prefix} ${entry.name}`;
                })
                .join("\n");

            return {
                content: [{
                    type: "text",
                    text: formatted || "Empty directory"
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "directory_tree",
    "Get a recursive tree view of files and directories as a JSON structure.",
    {
        path: z.string().describe("The path to the directory"),
        maxDepth: z.number().optional().default(10).describe("Maximum depth to traverse"),
        includeFiles: z.boolean().optional().default(true).describe("Include files in the output"),
        showHidden: z.boolean().optional().default(false).describe("Show hidden files starting with .")
    },
    async ({ path: dirPath, maxDepth, includeFiles, showHidden }) => {
        try {
            async function buildTree(currentPath, depth = 0) {
                if (depth >= maxDepth) {
                    return [{ name: "...", type: 'max-depth-reached' }];
                }

                let resolvedPath;
                try {
                    resolvedPath = await resolvePath(currentPath);
                } catch (error) {
                    return [{ name: path.basename(currentPath), type: 'error', error: error.message }];
                }

                let entries;
                try {
                    entries = await fs.readdir(resolvedPath, { withFileTypes: true });
                } catch (error) {
                    return [{ name: path.basename(currentPath), type: 'error', error: error.message }];
                }

                // 숨김 파일 필터링
                const filteredEntries = showHidden
                    ? entries
                    : entries.filter(entry => !entry.name.startsWith('.'));

                // 파일 필터링 (옵션)
                const filteredByType = includeFiles
                    ? filteredEntries
                    : filteredEntries.filter(entry => entry.isDirectory());

                // 디렉토리 먼저, 그 다음 파일 순으로 정렬
                const sortedEntries = filteredByType.sort((a, b) => {
                    if (a.isDirectory() && !b.isDirectory()) return -1;
                    if (!a.isDirectory() && b.isDirectory()) return 1;
                    return a.name.localeCompare(b.name);
                });

                const result = [];

                for (const entry of sortedEntries) {
                    let entryType = 'file';
                    if (entry.isDirectory()) entryType = 'directory';
                    if (entry.isSymbolicLink()) entryType = 'symlink';

                    const entryData = {
                        name: entry.name,
                        type: entryType
                    };

                    if (entry.isDirectory()) {
                        const subPath = path.join(currentPath, entry.name);
                        try {
                            entryData.children = await buildTree(subPath, depth + 1);
                        } catch (error) {
                            // 접근할 수 없는 하위 디렉토리
                            entryData.children = [];
                            entryData.error = "Access error";
                        }
                    }

                    result.push(entryData);
                }

                return result;
            }

            const treeData = await buildTree(dirPath);
            return {
                content: [{
                    type: "text",
                    text: JSON.stringify(treeData, null, 2)
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "move_file",
    "Move or rename files and directories. Can move files between directories and rename them in a single operation.",
    {
        source: z.string().describe("The source file or directory path"),
        destination: z.string().describe("The destination file or directory path"),
        overwrite: z.boolean().optional().default(false).describe("Overwrite destination if it exists")
    },
    async ({ source, destination, overwrite }) => {
        try {
            const resolvedSourcePath = await resolvePath(source);
            const resolvedDestPath = await resolvePath(destination);

            // 대상이 이미 존재하는지 확인
            try {
                await fs.stat(resolvedDestPath);
                // 파일이 존재하고 덮어쓰기가 허용되지 않은 경우
                if (!overwrite) {
                    throw new Error(`대상 파일이 이미 존재합니다: ${destination}. 덮어쓰려면 overwrite=true를 사용하세요.`);
                }
                // 덮어쓰기가 허용된 경우, 기존 파일 삭제
                await fs.unlink(resolvedDestPath);
            } catch (error) {
                // 파일이 존재하지 않으면 정상 진행
                if (error.code !== 'ENOENT') {
                    throw error;
                }
            }

            // 부모 디렉토리 확인
            const destDir = path.dirname(resolvedDestPath);
            try {
                await fs.mkdir(destDir, { recursive: true });
            } catch (error) {
                // 이미 존재하면 무시
            }

            await fs.rename(resolvedSourcePath, resolvedDestPath);
            return {
                content: [{ type: "text", text: `Successfully moved ${source} to ${destination}` }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "search_files",
    "Recursively search for files and directories matching a pattern. Searches through all subdirectories from the starting path.",
    {
        path: z.string().describe("The starting directory path"),
        pattern: z.string().describe("The search pattern"),
        maxResults: z.number().optional().default(1000).describe("Maximum number of results to return"),
        maxDepth: z.number().optional().default(20).describe("Maximum depth to search"),
        excludePatterns: z.array(z.string()).optional().default([]).describe("Patterns to exclude from search"),
        searchContents: z.boolean().optional().default(false).describe("Search file contents instead of just names")
    },
    async ({ path: dirPath, pattern, maxResults, maxDepth, excludePatterns, searchContents }) => {
        try {
            const resolvedPath = await resolvePath(dirPath);
            const results = await searchFiles(
                resolvedPath,
                pattern,
                maxResults,
                maxDepth,
                excludePatterns,
                searchContents
            );

            return {
                content: [{
                    type: "text",
                    text: results.length > 0
                        ? `Found ${results.length} results${results.length >= maxResults ? ` (limited to ${maxResults})` : ''}:\n${results.join("\n")}`
                        : "No matches found"
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "get_file_info",
    "Retrieve detailed metadata about a file or directory. Returns comprehensive information including size, creation time, last modified time, permissions, and type.",
    {
        path: z.string().describe("The path to the file or directory")
    },
    async ({ path: filePath }) => {
        try {
            const resolvedPath = await resolvePath(filePath);
            const info = await getFileStats(resolvedPath);

            // 객체를 더 읽기 쉬운 형식으로 포맷팅
            const formattedInfo = {
                ...info,
                size: `${info.size} bytes (${formatFileSize(info.size)})`,
                created: info.created.toLocaleString(),
                modified: info.modified.toLocaleString(),
                accessed: info.accessed.toLocaleString()
            };

            return {
                content: [{
                    type: "text",
                    text: Object.entries(formattedInfo)
                        .map(([key, value]) => `${key}: ${value}`)
                        .join("\n")
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error: ${error.message}` }],
                isError: true
            };
        }
    }
);

server.tool(
    "list_directory_info",
    "Returns information about the filesystem server.",
    {},
    async () => {
        return {
            content: [{
                type: "text",
                text: `Filesystem server information:
Current working directory (pwd): ${process.cwd()}
Home directory: ${os.homedir()}
Platform: ${process.platform}
User: ${os.userInfo().username}
Hostname: ${os.hostname()}
OS: ${os.type()} ${os.release()}
Node.js version: ${process.version}
Unrestricted filesystem access enabled`
            }]
        };
    }
);

server.tool(
    "get_pwd",
    "Returns the current working directory (pwd), which is used as the base for relative paths.",
    {},
    async () => {
        try {
            const currentDirectory = process.cwd();
            return {
                content: [{
                    type: "text",
                    text: currentDirectory
                }]
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error getting current directory: ${error.message}` }],
                isError: true
            };
        }
    }
);

// Helper functions
function formatFileSize(bytes) {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let unitIndex = 0;
    let size = bytes;

    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }

    return `${size.toFixed(2)} ${units[unitIndex]}`;
}

// Start server
const transport = new StdioServerTransport();
server.connect(transport);
console.error("MCP Filesystem Server running on stdio");
console.error("Current working directory (pwd):", process.cwd());
console.error("Unrestricted filesystem access enabled");