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
              description: "时区（例如：Asia/Shanghai, UTC）。默认为系统时区"
            },
            locale: {
              type: "string",
              description: "用于本地化星期显示的区域设置。默认为 zh-CN"
            },
            includeTimestamp: {
              type: "boolean",
              description: "是否在结果中包含毫秒级时间戳。默认为 false"
            },
            hour12: {
              type: "boolean",
              description: "是否使用 12 小时制格式化时区时间。默认为 false"
            }
          }
        }
      },
      {
        name: "convert_timezone",
        description: "将指定时间从一个时区转换到另一个时区。支持使用 IANA 时区名称进行转换",
        inputSchema: {
          type: "object",
          properties: {
            time: {
              type: "string",
              description: "要转换的时间。支持 ISO 8601 格式（如 '2024-03-15T10:30:00'）或时间戳（毫秒）。如果未提供，使用当前时间"
            },
            from_timezone: {
              type: "string",
              description: "源时区（例如：Asia/Shanghai, UTC, America/New_York）。如果未提供，使用系统时区"
            },
            to_timezone: {
              type: "string",
              description: "目标时区（例如：Asia/Tokyo, Europe/London）。必填参数"
            },
            format: {
              type: "string",
              description: "输出格式：'iso'（ISO 8601）、'locale'（本地格式）、'timestamp'（时间戳）。默认为 'iso'",
              enum: ["iso", "locale", "timestamp"]
            },
            include_dst_info: {
              type: "boolean",
              description: "是否包含夏令时（DST）信息。默认为 false"
            },
            include_offset: {
              type: "boolean",
              description: "是否包含 UTC 偏移信息（如 +08:00）。默认为 false"
            },
            output_locale: {
              type: "string",
              description: "用于 'locale' 格式的区域设置（如 'en-US', 'ja-JP'）。默认为 'zh-CN'"
            },
            include_time_difference: {
              type: "boolean",
              description: "是否包含源时区和目标时区之间的时间差（以小时为单位）。默认为 false"
            },
            include_timezone_abbr: {
              type: "boolean",
              description: "是否包含时区缩写（如 CST, EST, JST）。默认为 false"
            },
            compare_with_utc: {
              type: "boolean",
              description: "是否同时显示 UTC 时间以便对比。默认为 false"
            }
          },
          required: ["to_timezone"]
        }
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
          hour12: hour12
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
          timezone: timezone
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
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
        };
      }

      if (includeTimestamp) {
        dateInfo.timestamp = now.getTime();
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(dateInfo, null, 2)
          }
        ]
      };
    }

    if (name === "convert_timezone") {
      const timeInput = args?.time;
      const fromTimezone = args?.from_timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
      const toTimezone = args?.to_timezone;
      const format = args?.format || "iso";
      const includeDstInfo = args?.include_dst_info === true;
      const includeOffset = args?.include_offset === true;
      const outputLocale = args?.output_locale || "zh-CN";
      const includeTimeDifference = args?.include_time_difference === true;
      const includeTimezoneAbbr = args?.include_timezone_abbr === true;
      const compareWithUtc = args?.compare_with_utc === true;

      if (!toTimezone) {
        throw new Error("目标时区 (to_timezone) 是必填参数");
      }

      let sourceDate;
      if (timeInput) {
        const timestamp = parseInt(timeInput);
        if (!isNaN(timestamp)) {
          sourceDate = new Date(timestamp);
        } else {
          sourceDate = new Date(timeInput);
        }
        if (isNaN(sourceDate.getTime())) {
          throw new Error("无效的时间格式");
        }
      } else {
        sourceDate = new Date();
      }

      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: toTimezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
      });
      const parts = formatter.formatToParts(sourceDate);
      const year = parts.find((p) => p.type === "year").value;
      const month = parts.find((p) => p.type === "month").value;
      const day = parts.find((p) => p.type === "day").value;
      const hour = parts.find((p) => p.type === "hour").value;
      const minute = parts.find((p) => p.type === "minute").value;
      const second = parts.find((p) => p.type === "second").value;
      const convertedDate = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}`);

      let result;
      switch (format) {
        case "timestamp":
          result = sourceDate.getTime().toString();
          break;
        case "locale":
          result = sourceDate.toLocaleString(outputLocale, { timeZone: toTimezone });
          break;
        case "iso":
        default:
          result = sourceDate.toLocaleString("sv-SE", { timeZone: toTimezone }).replace(" ", "T");
          break;
      }

      const responseData = {
        original_time: timeInput || sourceDate.toISOString(),
        from_timezone: fromTimezone,
        to_timezone: toTimezone,
        converted_time: result,
        format: format
      };

      if (includeOffset) {
        const getOffset = (date, tz) => {
          const tzFormatter = new Intl.DateTimeFormat("en-US", {
            timeZone: tz,
            timeZoneName: "longOffset"
          });
          const tzParts = tzFormatter.formatToParts(date);
          const offsetPart = tzParts.find(p => p.type === "timeZoneName");
          if (offsetPart && offsetPart.value.startsWith("GMT")) {
            return offsetPart.value.replace("GMT", "") || "+00:00";
          }
          return "N/A";
        };
        responseData.from_offset = getOffset(sourceDate, fromTimezone);
        responseData.to_offset = getOffset(sourceDate, toTimezone);
      }

      if (includeDstInfo) {
        const isDST = (date, tz) => {
          const jan = new Date(date.getFullYear(), 0, 1);
          const jul = new Date(date.getFullYear(), 6, 1);
          const janFormatter = new Intl.DateTimeFormat("en-US", {
            timeZone: tz,
            hour: "numeric",
            hour12: false
          });
          const julFormatter = new Intl.DateTimeFormat("en-US", {
            timeZone: tz,
            hour: "numeric",
            hour12: false
          });
          const currentFormatter = new Intl.DateTimeFormat("en-US", {
            timeZone: tz,
            hour: "numeric",
            hour12: false
          });
          const janOffset = new Date(janFormatter.format(jan)).getTimezoneOffset();
          const julOffset = new Date(julFormatter.format(jul)).getTimezoneOffset();
          const currentOffset = new Date(currentFormatter.format(date)).getTimezoneOffset();
          const stdOffset = Math.max(janOffset, julOffset);
          return currentOffset < stdOffset;
        };
        responseData.from_dst_active = isDST(sourceDate, fromTimezone);
        responseData.to_dst_active = isDST(sourceDate, toTimezone);
      }

      if (includeTimeDifference) {
        const getOffsetMinutes = (date, tz) => {
          const utcDate = new Date(date.toLocaleString("en-US", { timeZone: "UTC" }));
          const tzDate = new Date(date.toLocaleString("en-US", { timeZone: tz }));
          return (tzDate - utcDate) / (1000 * 60);
        };
        const fromOffsetMinutes = getOffsetMinutes(sourceDate, fromTimezone);
        const toOffsetMinutes = getOffsetMinutes(sourceDate, toTimezone);
        const differenceMinutes = toOffsetMinutes - fromOffsetMinutes;
        const differenceHours = differenceMinutes / 60;
        responseData.time_difference_hours = differenceHours;
        responseData.time_difference_description = differenceHours >= 0 
          ? `目标时区比源时区快 ${Math.abs(differenceHours)} 小时` 
          : `目标时区比源时区慢 ${Math.abs(differenceHours)} 小时`;
      }

      if (includeTimezoneAbbr) {
        const getTimezoneAbbr = (date, tz) => {
          const formatter = new Intl.DateTimeFormat("en-US", {
            timeZone: tz,
            timeZoneName: "short"
          });
          const parts = formatter.formatToParts(date);
          const abbrPart = parts.find(p => p.type === "timeZoneName");
          return abbrPart ? abbrPart.value : "N/A";
        };
        responseData.from_timezone_abbr = getTimezoneAbbr(sourceDate, fromTimezone);
        responseData.to_timezone_abbr = getTimezoneAbbr(sourceDate, toTimezone);
      }

      if (compareWithUtc) {
        let utcResult;
        switch (format) {
          case "timestamp":
            utcResult = sourceDate.getTime().toString();
            break;
          case "locale":
            utcResult = sourceDate.toLocaleString(outputLocale, { timeZone: "UTC" });
            break;
          case "iso":
          default:
            utcResult = sourceDate.toISOString();
            break;
        }
        responseData.utc_time = utcResult;
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(responseData, null, 2)
          }
        ]
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