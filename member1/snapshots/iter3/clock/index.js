#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  {
    name: "mcp-server-time",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// 列出可用工具
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "get_current_time",
        description: "获取当前日期和时间",
        inputSchema: {
          type: "object",
          properties: {
            timezone: {
              type: "string",
              description: "时区（例如：Asia/Shanghai, UTC, America/New_York）。默认为系统时区",
            },
            format: {
              type: "string",
              description: "时间格式：'iso'（ISO 8601）、'locale'（本地格式）、'timestamp'（时间戳）。默认为 'iso'",
              enum: ["iso", "locale", "timestamp"],
            },
          },
        },
      },
      {
        name: "get_time_info",
        description: "获取详细的时间信息，包括年、月、日、时、分、秒等",
        inputSchema: {
          type: "object",
          properties: {
            timezone: {
              type: "string",
              description: "时区（例如：Asia/Shanghai, UTC）。默认为系统时区",
            },
            locale: {
              type: "string",
              description: "用于本地化星期显示的区域设置。默认为 zh-CN",
            },
            includeTimestamp: {
              type: "boolean",
              description: "是否在结果中包含毫秒级时间戳。默认为 false",
            },
            hour12: {
              type: "boolean",
              description: "是否使用 12 小时制格式化时区时间。默认为 false",
            },
          },
        },
      },
    ],
  };
});

// 处理工具调用
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    if (name === "get_current_time") {
      const timezone = args?.timezone || undefined;
      const format = args?.format || "iso";

      let date;
      if (timezone) {
        // 使用指定时区
        const now = new Date();
        const formatter = new Intl.DateTimeFormat("en-US", {
          timeZone: timezone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
        const parts = formatter.formatToParts(now);
        const year = parts.find((p) => p.type === "year").value;
        const month = parts.find((p) => p.type === "month").value;
        const day = parts.find((p) => p.type === "day").value;
        const hour = parts.find((p) => p.type === "hour").value;
        const minute = parts.find((p) => p.type === "minute").value;
        const second = parts.find((p) => p.type === "second").value;
        date = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}`);
      } else {
        date = new Date();
      }

      let result;
      switch (format) {
        case "timestamp":
          result = date.getTime().toString();
          break;
        case "locale":
          result = date.toLocaleString("zh-CN", timezone ? { timeZone: timezone } : {});
          break;
        case "iso":
        default:
          result = date.toISOString();
          break;
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              time: result,
              timezone: timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
              format: format,
            }, null, 2),
          },
        ],
      };
    }

    if (name === "get_time_info") {
      const timezone = args?.timezone || undefined;
      const locale = args?.locale || "zh-CN";
      const includeTimestamp = args?.includeTimestamp === true;
      const hour12 = args?.hour12 === true;
      const now = new Date();

      let dateInfo;
      if (timezone) {
        const formatter = new Intl.DateTimeFormat(locale, {
          timeZone: timezone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          weekday: "long",
          hour12: hour12,
        });
        const parts = formatter.formatToParts(now);
        dateInfo = {
          year: parseInt(parts.find((p) => p.type === "year").value),
          month: parseInt(parts.find((p) => p.type === "month").value),
          day: parseInt(parts.find((p) => p.type === "day").value),
          hour: parseInt(parts.find((p) => p.type === "hour").value),
          minute: parseInt(parts.find((p) => p.type === "minute").value),
          second: parseInt(parts.find((p) => p.type === "second").value),
          weekday: parts.find((p) => p.type === "weekday").value,
          timezone: timezone,
        };
      } else {
        dateInfo = {
          year: now.getFullYear(),
          month: now.getMonth() + 1,
          day: now.getDate(),
          hour: now.getHours(),
          minute: now.getMinutes(),
          second: now.getSeconds(),
          weekday: now.toLocaleDateString(locale, { weekday: "long" }),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };
      }

      if (includeTimestamp) {
        dateInfo.timestamp = now.getTime();
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(dateInfo, null, 2),
          },
        ],
      };
    }

    throw new Error(`未知的工具: ${name}`);
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: `错误: ${error.message}`,
        },
      ],
      isError: true,
    };
  }
});

// 启动服务器
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("MCP 时间服务器已启动");
}

main().catch((error) => {
  console.error("服务器启动失败:", error);
  process.exit(1);
});