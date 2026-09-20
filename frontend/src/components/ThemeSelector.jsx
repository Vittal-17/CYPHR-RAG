import React, { useEffect, useState } from 'react';
import { Sun, Moon, Monitor } from 'lucide-react';
import clsx from 'clsx';

const ThemeSelector = () => {
  const [theme, setTheme] = useState('light');
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem('cyphr-theme') || 'light';
    setTheme(saved);
  }, []);

  const changeTheme = (newTheme) => {
    setTheme(newTheme);
    localStorage.setItem('cyphr-theme', newTheme);

    const isDark = newTheme === 'dark' || (newTheme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    document.documentElement.style.backgroundColor = isDark ? '#02060e' : '#f8fcff';
    setIsOpen(false);
  };

  const themes = [
    { id: 'light', label: 'Light', icon: Sun },
    { id: 'dark', label: 'Dark', icon: Moon },
    { id: 'system', label: 'System', icon: Monitor },
  ];

  const CurrentIcon = themes.find((t) => t.id === theme)?.icon || Sun;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="icon-btn tip tip-below relative"
        data-tip="Theme"
        aria-label="Select theme"
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        <CurrentIcon className="h-4 w-4 text-ink-dim hover:text-ink transition-colors" />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-chrome" onClick={() => setIsOpen(false)} />
          <div
            className="absolute right-0 top-full mt-1.5 w-36 overflow-hidden rounded-lg border border-line bg-surface-2 shadow-panel z-overlay animate-scale-in origin-top-right"
            role="menu"
            aria-label="Theme selection"
          >
            <div className="flex flex-col py-1">
              {themes.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={theme === t.id}
                  onClick={() => changeTheme(t.id)}
                  className={clsx(
                    'flex items-center gap-2.5 px-3 py-2 text-sub font-medium transition-all duration-fast ease-standard hover:-translate-y-px hover:shadow-subtle hover:bg-surface-3',
                    theme === t.id ? 'text-accent bg-accent/10 shadow-subtle' : 'text-ink-dim hover:text-ink'
                  )}
                >
                  <t.icon className="h-4 w-4" />
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default ThemeSelector;
