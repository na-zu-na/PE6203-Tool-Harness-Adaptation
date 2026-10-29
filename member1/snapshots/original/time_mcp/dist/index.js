#!/usr/bin/env node

// src/index.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import dayjs from "dayjs";
import isoWeek from "dayjs/plugin/isoWeek.js";
import relativeTime from "dayjs/plugin/relativeTime.js";
import timezone from "dayjs/plugin/timezone.js";
import utc from "dayjs/plugin/utc.js";
import weekOfYear from "dayjs/plugin/weekOfYear.js";

// src/tools.ts
import { z } from "zod/v4";
var CURRENT_TIME = {
  name: "current_time",
  description: "Get the current date and time.",
  schema: z.object({
    format: z.enum([
      "h:mm A",
      "h:mm:ss A",
      "YYYY-MM-DD HH:mm:ss",
      "YYYY-MM-DD",
      "YYYY-MM",
      "MM/DD/YYYY",
      "MM/DD/YY",
      "YYYY/MM/DD",
      "YYYY/MM"
    ]).describe("The format of the time").default("YYYY-MM-DD HH:mm:ss"),
    timezone: z.string().describe("The timezone of the time, IANA timezone name, e.g. Asia/Shanghai").optional()
  })
};
var RELATIVE_TIME = {
  name: "relative_time",
  description: "Get the relative time from now.",
  schema: z.object({
    time: z.string().describe("The time to get the relative time from now. Format: YYYY-MM-DD HH:mm:ss")
  })
};
var DAYS_IN_MONTH = {
  name: "days_in_month",
  description: "Get the number of days in a month. If no date is provided, get the number of days in the current month.",
  schema: z.object({
    date: z.string().describe("The date to get the days in month. Format: YYYY-MM-DD").optional()
  })
};
var GET_TIMESTAMP = {
  name: "get_timestamp",
  description: "Get the timestamp for the time.",
  schema: z.object({
    time: z.string().describe("The time to get the timestamp. Format: YYYY-MM-DD HH:mm:ss.SSS").optional()
  })
};
var CONVERT_TIME = {
  name: "convert_time",
  description: "Convert time between timezones.",
  schema: z.object({
    sourceTimezone: z.string().describe("The source timezone. IANA timezone name, e.g. Asia/Shanghai"),
    targetTimezone: z.string().describe("The target timezone. IANA timezone name, e.g. Europe/London"),
    time: z.string().describe("Date and time in 24-hour format. e.g. 2025-03-23 12:30:00")
  })
};
var GET_WEEK_YEAR = {
  name: "get_week_year",
  description: "Get the week and isoWeek of the year.",
  schema: z.object({
    date: z.string().describe("The date to get the week and isoWeek of the year. e.g. 2025-03-23").optional()
  })
};

// src/index.ts
dayjs.extend(relativeTime);
dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(weekOfYear);
dayjs.extend(isoWeek);
function getCurrentTime(format, timezone2) {
  const utcTime = dayjs.utc();
  const localTimezone = timezone2 ?? dayjs.tz.guess();
  const localTime = utcTime.tz(localTimezone);
  return {
    utc: utcTime.format(format),
    local: localTime.format(format),
    timezone: localTimezone
  };
}
function getRelativeTime(time) {
  return dayjs(time).fromNow();
}
function getTimestamp(time) {
  return time ? dayjs.utc(time).valueOf() : dayjs().valueOf();
}
function getDaysInMonth(date) {
  return date ? dayjs(date).daysInMonth() : dayjs().daysInMonth();
}
function getWeekOfYear(date) {
  const week = date ? dayjs(date).week() : dayjs().week();
  const isoWeek2 = date ? dayjs(date).isoWeek() : dayjs().isoWeek();
  return {
    week,
    isoWeek: isoWeek2
  };
}
function convertTime(sourceTimezone, targetTimezone, time) {
  const sourceTime = time ? dayjs.tz(time, sourceTimezone) : dayjs().tz(sourceTimezone);
  const targetTime = sourceTime.tz(targetTimezone);
  const formatString = "YYYY-MM-DD HH:mm:ss";
  const timeDiffMinutes = targetTime.utcOffset() - sourceTime.utcOffset();
  return {
    sourceTime: sourceTime.format(formatString),
    targetTime: targetTime.format(formatString),
    timeDiff: timeDiffMinutes / 60
  };
}
var server = new McpServer({
  name: "time-mcp",
  version: "1.0.6"
}, {
  capabilities: {
    tools: {},
    logging: {}
  }
});
server.registerTool(
  CURRENT_TIME.name,
  {
    description: CURRENT_TIME.description,
    inputSchema: CURRENT_TIME.schema
  },
  (args) => {
    const result = getCurrentTime(args.format, args.timezone);
    return {
      content: [
        {
          type: "text",
          text: `Current UTC time is ${result.utc}, and the time in ${result.timezone} is ${result.local}.`
        }
      ]
    };
  }
);
server.registerTool(
  RELATIVE_TIME.name,
  {
    description: RELATIVE_TIME.description,
    inputSchema: RELATIVE_TIME.schema
  },
  (args) => {
    const result = getRelativeTime(args.time);
    return {
      content: [
        {
          type: "text",
          text: result
        }
      ]
    };
  }
);
server.registerTool(
  DAYS_IN_MONTH.name,
  {
    description: DAYS_IN_MONTH.description,
    inputSchema: DAYS_IN_MONTH.schema
  },
  (args) => {
    const result = getDaysInMonth(args.date);
    return {
      content: [
        {
          type: "text",
          text: `The number of days in month is ${result}.`
        }
      ]
    };
  }
);
server.registerTool(
  GET_TIMESTAMP.name,
  {
    description: GET_TIMESTAMP.description,
    inputSchema: GET_TIMESTAMP.schema
  },
  (args) => {
    const result = getTimestamp(args.time);
    return {
      content: [
        {
          type: "text",
          text: args.time ? `The timestamp of ${args.time} (parsed as UTC) is ${result} ms.` : `The current timestamp is ${result} ms.`
        }
      ]
    };
  }
);
server.registerTool(
  CONVERT_TIME.name,
  {
    description: CONVERT_TIME.description,
    inputSchema: CONVERT_TIME.schema
  },
  (args) => {
    const { sourceTime, targetTime, timeDiff } = convertTime(args.sourceTimezone, args.targetTimezone, args.time);
    return {
      content: [
        {
          type: "text",
          text: `Current time in ${args.sourceTimezone} is ${sourceTime}, and the time in ${args.targetTimezone} is ${targetTime}. The time difference is ${timeDiff} hours.`
        }
      ]
    };
  }
);
server.registerTool(
  GET_WEEK_YEAR.name,
  {
    description: GET_WEEK_YEAR.description,
    inputSchema: GET_WEEK_YEAR.schema
  },
  (args) => {
    const { week, isoWeek: isoWeek2 } = getWeekOfYear(args.date);
    return {
      content: [
        {
          type: "text",
          text: `The week of the year is ${week}, and the isoWeek of the year is ${isoWeek2}.`
        }
      ]
    };
  }
);
async function runServer() {
  try {
    process.stdout.write("Starting Time MCP server...\n");
    const transport = new StdioServerTransport();
    await server.connect(transport);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Error starting Time MCP server: ${message}
`);
    process.exit(1);
  }
}
runServer().catch((error) => {
  const errorMessage = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Error running Time MCP server: ${errorMessage}
`);
  process.exit(1);
});
//# sourceMappingURL=index.js.map