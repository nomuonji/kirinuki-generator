import React from "react";
import {DesignProps} from "./shared";
import {Cinema, CINEMA_VARIANTS} from "./templates/Cinema";
import {Gougai, GOUGAI_VARIANTS} from "./templates/Gougai";
import {Note, NOTE_VARIANTS} from "./templates/Note";
import {Pop, POP_VARIANTS} from "./templates/Pop";
import {Terminal, TERMINAL_VARIANTS} from "./templates/Terminal";

/**
 * Template ids are stored in the publish ledger, so never rename one. The Python rotation
 * (packages/design_rotation.py) keeps its own copy of these ids and variant counts; the
 * operations tests compare the two.
 */
export const TEMPLATES = {
  gougai: {component: Gougai, variants: GOUGAI_VARIANTS},
  terminal: {component: Terminal, variants: TERMINAL_VARIANTS},
  pop: {component: Pop, variants: POP_VARIANTS},
  cinema: {component: Cinema, variants: CINEMA_VARIANTS},
  note: {component: Note, variants: NOTE_VARIANTS},
} satisfies Record<string, {component: React.FC<DesignProps>; variants: number}>;

export type TemplateId = keyof typeof TEMPLATES;
export const TEMPLATE_IDS = Object.keys(TEMPLATES) as TemplateId[];
