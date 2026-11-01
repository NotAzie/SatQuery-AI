import type { AgentEvent, EarthCommand } from "@/shared/types";

export type EarthCommandHandlers = {
  [CommandType in EarthCommand["type"]]?: (
    command: Extract<EarthCommand, { type: CommandType }>,
  ) => void | Promise<void>;
};

export interface EarthCommandDispatcher {
  /** Applies a command only when it is carried by a typed Earth command event. */
  dispatch(event: AgentEvent): Promise<boolean>;
}

export class UnsupportedEarthCommandError extends Error {
  constructor(commandType: EarthCommand["type"]) {
    super(`Earth command '${commandType}' has no registered workspace handler`);
    this.name = "UnsupportedEarthCommandError";
  }
}

/**
 * Routes presentation commands from the Engine event stream to workspace controllers.
 * It never accepts a bare command, so UI code cannot accidentally invent Earth actions.
 */
export function createEarthCommandDispatcher(
  handlers: EarthCommandHandlers,
): EarthCommandDispatcher {
  return {
    async dispatch(event) {
      if (event.type !== "earth.command") return false;
      const command = event.command;
      switch (command.type) {
        case "fly_to":
          await requireHandler(handlers.fly_to, command)(command);
          break;
        case "set_time":
          await requireHandler(handlers.set_time, command)(command);
          break;
        case "set_layer_visibility":
          await requireHandler(handlers.set_layer_visibility, command)(command);
          break;
        case "add_overlay":
          await requireHandler(handlers.add_overlay, command)(command);
          break;
        case "clear_overlays":
          await requireHandler(handlers.clear_overlays, command)(command);
          break;
        case "highlight_evidence":
          await requireHandler(handlers.highlight_evidence, command)(command);
          break;
        case "show_investigation":
          await requireHandler(handlers.show_investigation, command)(command);
          break;
      }
      return true;
    },
  };
}

function requireHandler<Command extends EarthCommand>(
  handler: ((command: Command) => void | Promise<void>) | undefined,
  command: Command,
): (command: Command) => void | Promise<void> {
  if (!handler) throw new UnsupportedEarthCommandError(command.type);
  return handler;
}
