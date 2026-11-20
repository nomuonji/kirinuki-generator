import React from "react";
import {AbsoluteFill, OffthreadVideo} from "remotion";
import {FONT, SAFE, SubtitleEntry, ReactionEntry, useFontsReady, useSubtitle, useReaction} from "./design/shared";

/** Render-only properties. Editorial/video titles are intentionally not accepted here. */
export type CleanShortProps = {
  src: string;
  aspect: number;
  subtitles: SubtitleEntry[];
  editorialHook?: string;
  reactions: ReactionEntry[];
  mascot?: {enabled: boolean; size?: number; right?: number; insetTop?: number};
};

/** Original, geometric mascot. Not an ABEMA/Today Suki program character. */
const OriginalMascot: React.FC = () => (
  <svg viewBox="0 0 120 120" width="100%" height="100%" aria-label="original mascot">
    <path d="M23 39 Q13 10 39 20 L51 34 Q68 26 81 35 L98 19 Q114 11 101 49 Q114 66 103 88 Q90 111 58 108 Q25 108 16 84 Q8 61 23 39Z"
      fill="#fff9ef" stroke="#34475e" strokeWidth="6" strokeLinejoin="round"/>
    <path d="M28 28 L41 35 L27 45Z M92 27 L83 38 L101 44Z" fill="#ffbccc"/>
    <ellipse cx="44" cy="64" rx="5.2" ry="7.2" fill="#34475e"/>
    <ellipse cx="78" cy="64" rx="5.2" ry="7.2" fill="#34475e"/>
    <path d="M56 78 Q62 84 68 78" fill="none" stroke="#34475e" strokeWidth="4" strokeLinecap="round"/>
    <circle cx="32" cy="78" r="8" fill="#ffa6b8" opacity=".67"/>
    <circle cx="91" cy="78" r="8" fill="#ffa6b8" opacity=".67"/>
    <path d="M60 30 Q51 10 57 8 M61 27 Q72 14 74 9" fill="none" stroke="#76b97b" strokeWidth="5" strokeLinecap="round"/>
  </svg>
);

export const CleanShort: React.FC<CleanShortProps> = (p) => {
  useFontsReady(["900 64px 'Noto Sans JP'"], p.subtitles.map(s => s.text).join(""));
  const isVertical = p.aspect < 0.85;
  const videoTop = isVertical ? 0 : 360;
  const videoHeight = isVertical ? 1920 : 1120;
  const sub = useSubtitle(p.subtitles);
  const reaction = useReaction(p.reactions);
  const characters = sub.entry ? [...sub.entry.text].length : 0;
  const fontSize = Math.max(40, Math.min(65, Math.floor(900 / Math.max(10, characters / 1.65))));
  const showMascot = p.mascot?.enabled === true;
  const hook = (p.editorialHook ?? "").trim();
  const hookLength = hook.replace(/\\*\\*/g,"").length;
  // Only the authored editorial hook is shown; sourceVideoTitle and episode banners are never rendered.
  return (
    <AbsoluteFill style={{backgroundColor:"#080b15", overflow:"hidden"}}>
      <AbsoluteFill style={{overflow:"hidden",backgroundColor:"#151923"}}>
        <OffthreadVideo muted src={p.src} style={{width:"100%",height:"100%",
          objectFit:"cover",filter:"blur(65px) brightness(0.36)",transform:"scale(1.15)"}} />
      </AbsoluteFill>
      <div style={{position:"absolute",left:0,top:videoTop,width:1080,height:videoHeight,overflow:"hidden"}}>
        <OffthreadVideo src={p.src} style={{width:"100%",height:"100%",objectFit:"contain",objectPosition:"center center"}}/>
      </div>
      {hook && (
        <div style={{position:"absolute",top:124,left:64,right:64,
          zIndex:3,textAlign:"center",fontFamily:FONT.sans,
          fontWeight:900,color:"#fff",lineHeight:1.28,
          fontSize:hookLength>19?54:hookLength>14?53:60,
          overflowWrap:"anywhere",wordBreak:"break-word",
          textShadow:"0 3px 8px rgba(0,0,0,.9), 0 0 5px rgba(0,0,0,.9)"}}>
          {hook.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((chunk, i) => {
            const emph=chunk.startsWith("**") && chunk.endsWith("**");
            return <span key={i} style={{color:emph?"#FFD500":"#fff"}}>
              {emph?chunk.slice(2,-2):chunk}
            </span>;
          })}
        </div>
      )}
      {reaction.entry && (
        <div style={{position:"absolute",top:videoTop+225,left:SAFE.left,right:210,
          fontFamily:FONT.sans,fontSize:50,fontWeight:900,color:"#fff",
          textShadow:"0 3px 8px #000, 0 0 7px #000",lineHeight:1.2}}>
          {reaction.entry.text}
        </div>
      )}
      {sub.entry && (
        <div style={{position:"absolute",bottom:516,left:SAFE.left,right:1080-SAFE.right,
          padding:"15px 18px",borderRadius:12,background:"rgba(0,0,0,.46)",
          textAlign:"center",fontFamily:FONT.sans,fontWeight:900,
          fontSize,lineHeight:1.32,color:"#fff",whiteSpace:"pre-wrap",
          textShadow:"0 2px 5px #000, 0 0 8px #000"}}>
          {sub.entry.text}
        </div>
      )}
      {showMascot && (
        <div style={{position:"absolute",top:videoTop+(p.mascot?.insetTop ?? (isVertical ? 44 : 282)),
          right:p.mascot?.right ?? 58,width:p.mascot?.size ?? 126,height:p.mascot?.size ?? 126,
          filter:"drop-shadow(0 4px 8px rgba(0,0,0,.46))"}}>
          <OriginalMascot />
        </div>
      )}
    </AbsoluteFill>
  );
};
