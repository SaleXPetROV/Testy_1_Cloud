/**
 * SmartAvatar — renders a user avatar regardless of its shape.
 *
 * `avatar` may be:
 *   • a string URL / data-URI               → <img>
 *   • { type: 'url', url }                   → <img>
 *   • { type: 'initials', initials, color }  → colored initials tile
 *   • null / undefined / anything else       → initials from `name`
 *
 * This prevents the "[object Object]" broken-image bug where an object avatar
 * was passed straight into <img src=…>.
 */
import { useState } from 'react';

export default function SmartAvatar({ avatar, name, className = '', textClassName = '' }) {
  const [broken, setBroken] = useState(false);
  const fallbackInitials = ((name || 'U').trim()[0] || 'U').toUpperCase();

  let url = null;
  let initials = null;
  let bg = null;

  if (typeof avatar === 'string' && avatar) {
    url = avatar;
  } else if (avatar && typeof avatar === 'object') {
    if (avatar.type === 'url' && avatar.url) {
      url = avatar.url;
    } else if (avatar.type === 'initials') {
      initials = (avatar.initials || fallbackInitials).toString().toUpperCase();
      bg = avatar.color || null;
    } else if (avatar.url) {
      url = avatar.url;
    }
  }

  if (url && !broken) {
    return (
      <img
        src={url}
        alt={name || ''}
        className={`object-cover ${className}`}
        onError={() => setBroken(true)}
        data-testid="smart-avatar-img"
      />
    );
  }

  return (
    <div
      className={`flex items-center justify-center font-bold text-black ${className} ${bg ? '' : 'bg-gradient-to-br from-cyber-cyan to-neon-purple'}`}
      style={bg ? { background: bg, color: '#fff' } : undefined}
      data-testid="smart-avatar-initials"
    >
      <span className={textClassName}>{initials || fallbackInitials}</span>
    </div>
  );
}
