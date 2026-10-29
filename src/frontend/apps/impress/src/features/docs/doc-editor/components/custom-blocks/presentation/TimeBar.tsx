import { RefObject, useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, Text } from '@/components';

// The time bar of an animation: readers pause it and move forward or back.
//
// The presentation runs sealed (no access to the page), so the page can't
// reach into it: a small helper goes in with it (withTimeline) and the two
// only exchange numbers, by messages. The helper measures how long the
// animation lasts from what the browser knows of its animations (CSS
// animations and transitions, element.animate()), or asks the file's own
// handle (window.collaboratorsTimeline, see the backend's guide) for one
// driven by a script; one that can't be measured (endless, or a script
// without a handle) says 0 seconds, and no time bar is offered.

export const TIME_MESSAGE = 'collaborators:time';

const HELPER = `(function () {
  var TYPE = '${TIME_MESSAGE}';
  var starts = typeof WeakMap === 'function' ? new WeakMap() : null;
  // its time counts from when its first animation started
  var origin = null, offset = 0, since = 0, playing = true, sent = '';
  var now = function () { return performance.now(); };
  var clock = function () { return offset + (playing ? (now() - since) / 1000 : 0); };
  var handle = function () {
    var h = window.collaboratorsTimeline;
    return h && typeof h.seek === 'function' && isFinite(+h.duration) && +h.duration > 0 ? h : null;
  };
  var animations = function () {
    var list = document.getAnimations ? document.getAnimations() : [];
    var at = document.timeline ? document.timeline.currentTime || 0 : 0;
    list.forEach(function (a) {
      if (starts && !starts.has(a)) {
        var start = a.startTime != null ? a.startTime : at - (a.currentTime || 0);
        starts.set(a, start);
        if (origin === null || start < origin) { origin = start; }
      }
    });
    return list;
  };
  var startOf = function (a) { return (starts ? starts.get(a) : 0) - (origin || 0); };
  var endOf = function (a) {
    var timing = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
    return timing ? timing.endTime : Infinity;
  };
  var length = function () {
    var h = handle();
    if (h) { return +h.duration; }
    var list = animations(), end = 0;
    for (var i = 0; i < list.length; i++) {
      var last = endOf(list[i]);
      if (!isFinite(last)) { return 0; }
      end = Math.max(end, startOf(list[i]) + last);
    }
    return end / 1000;
  };
  var apply = function (seconds) {
    var h = handle();
    if (h) {
      h.seek(seconds);
      if (playing && h.play) { h.play(); } else if (!playing && h.pause) { h.pause(); }
    } else {
      animations().forEach(function (a) {
        var end = endOf(a);
        var local = seconds * 1000 - startOf(a);
        if (local >= end) { a.currentTime = end; a.pause(); return; }
        a.currentTime = Math.max(0, local);
        if (playing) { a.play(); } else { a.pause(); }
      });
    }
    offset = seconds;
    since = now();
  };
  var report = function () {
    var seconds = length();
    if (seconds && playing && clock() >= seconds) { offset = seconds; playing = false; }
    var time = Math.min(clock(), seconds);
    var message = { type: TYPE, seconds: seconds, time: time, playing: playing };
    var key = [seconds.toFixed(1), time.toFixed(1), playing].join();
    if (key !== sent) { sent = key; parent.postMessage(message, '*'); }
  };
  addEventListener('message', function (event) {
    var data = event.data;
    if (event.source !== parent || !data || data.type !== TYPE) { return; }
    var total = length();
    if (!total) { return; }
    var at = Math.min(clock(), total);
    if (data.action === 'seek' && isFinite(+data.time)) {
      apply(Math.max(0, Math.min(total, +data.time)));
    } else if (data.action === 'play') {
      playing = true;
      apply(at >= total ? 0 : at);
    } else if (data.action === 'pause') {
      playing = false;
      apply(at);
    }
    sent = '';
    report();
  });
  addEventListener('load', function () {
    setTimeout(function () {
      animations();
      var at = document.timeline ? document.timeline.currentTime || 0 : 0;
      offset = handle() ? at / 1000 : Math.max(0, at - (origin || 0)) / 1000;
      since = now();
      report();
      setInterval(report, 250);
    }, 300);
  });
})();`;

const REFERRER_META = '<meta name="referrer" content="no-referrer">';

/**
 * The sealed document (sealedDocument) with the time bar's helper right
 * after its rules, before the file's own scripts.
 */
export const withTimeline = (sealed: string) => {
  const at = sealed.indexOf(REFERRER_META);
  if (at === -1) {
    return sealed;
  }
  const end = at + REFERRER_META.length;
  return `${sealed.slice(0, end)}<script>${HELPER}</script>${sealed.slice(end)}`;
};

export interface Timeline {
  /** How long it lasts; 0 when it can't be measured (no time bar then) */
  seconds: number;
  time: number;
  playing: boolean;
}

const NOT_MEASURED: Timeline = { seconds: 0, time: 0, playing: false };

/** What the presentation's helper says of its time, and how to move it. */
export const useTimeline = (frame: RefObject<HTMLIFrameElement | null>) => {
  const [timeline, setTimeline] = useState<Timeline>(NOT_MEASURED);

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      const data = event.data as Partial<Timeline> & { type?: string };
      // only its own frame, and only numbers: it runs whatever the file says
      if (
        !frame.current ||
        event.source !== frame.current.contentWindow ||
        data?.type !== TIME_MESSAGE
      ) {
        return;
      }
      const seconds = Number(data.seconds);
      const time = Number(data.time);
      if (!Number.isFinite(seconds) || !Number.isFinite(time)) {
        return;
      }
      setTimeline({
        seconds: Math.max(0, seconds),
        time: Math.max(0, Math.min(time, seconds)),
        playing: data.playing === true,
      });
    };
    window.addEventListener('message', listen);
    return () => window.removeEventListener('message', listen);
  }, [frame]);

  const send = useCallback(
    (action: 'play' | 'pause' | 'seek', time?: number) => {
      frame.current?.contentWindow?.postMessage(
        { type: TIME_MESSAGE, action, time },
        '*',
      );
    },
    [frame],
  );

  return { timeline, send };
};

/** "1:05" */
export const clockTime = (seconds: number) => {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
};

const barCss = css`
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  & button {
    background: none;
    border: 0;
    color: inherit;
    cursor: pointer;
    display: flex;
    padding: 2px;
  }
  & input {
    flex: 1;
    accent-color: #fff;
    min-width: 60px;
  }
`;

/** Play or pause, how far along, and a slider to move through it. */
export const TimeBar = ({
  timeline,
  send,
}: {
  timeline: Timeline;
  send: (action: 'play' | 'pause' | 'seek', time?: number) => void;
}) => {
  const { t } = useTranslation();
  return (
    <Box
      $direction="row"
      $align="center"
      $gap="xs"
      $padding={{ horizontal: 'xs', vertical: '2px' }}
      $css={barCss}
      data-testid="presentation-time-bar"
    >
      <button
        type="button"
        onClick={() => send(timeline.playing ? 'pause' : 'play')}
        aria-label={
          timeline.playing
            ? t('Pause', { description: 'Button pausing an animation' })
            : t('Play', { description: 'Button playing an animation' })
        }
      >
        <Icon
          iconName={timeline.playing ? 'pause' : 'play_arrow'}
          $size="20px"
          $color="inherit"
        />
      </button>
      <input
        type="range"
        min={0}
        max={timeline.seconds}
        step={0.1}
        value={timeline.time}
        aria-label={t('Time in the animation', {
          description: 'Label of the slider moving through an animation',
        })}
        onChange={(event) => send('seek', Number(event.target.value))}
      />
      <Text
        $size="xs"
        $color="inherit"
        $css="font-variant-numeric: tabular-nums;"
      >
        {clockTime(timeline.time)} / {clockTime(timeline.seconds)}
      </Text>
    </Box>
  );
};
