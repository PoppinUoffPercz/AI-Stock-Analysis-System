[System Instructions]
You are operating in Long-Horizon Engineering Agent Mode (Max Thinking). You have a 1M-token context window to execute this full development task end-to-end without placeholders, architectural drift, or truncated code blocks. Your goal is to write a production-ready, fully working Financial Trading & Analytics Dashboard featuring live-updating market data simulations and comprehensive client-side quantitative metrics.

[Tech Stack Constraints]
- Frontend: Single-file Next.js (App Router, React 19) or a self-contained Vite + React setup utilizing Tailwind CSS for styling.
- State Management: React Context or native `useReducer` to prevent fragmentation across real-time updates.
- Data Visualization: Lucide React for iconography, and Chart.js or Recharts for complex financial graphs.
- Live Data: Implement an internal mock SSE/WebSocket real-time worker or high-frequency interval generator (simulating a live API feed like Alpaca or Alpha Vantage) that mutates order books and tickers every 250ms.

[Core Feature Requirements]
1. Live Market Ticker & Order Book:
   - A real-time data table and marquee displaying active tickers (e.g., AAPL, LLY, ORCL, MSFT), bid/ask spreads, and a dynamically shifting Level 2 Order Book (Bid/Ask depth).
2. Quantitative Analytics Engine:
   - Client-side calculations updating in real-time: Simple Moving Averages (SMA-20, SMA-50), Exponential Moving Averages (EMA), Relative Strength Index (RSI-14), and Moving Average Convergence Divergence (MACD).
   - Implement basic Volatility tracking (Rolling Standard Deviation of price changes).
3. Interactive Trading Terminal:
   - Form controls to place simulated "Market" and "Limit" orders (Buy/Sell).
   - A running "Portfolio Value" component tracking dynamic PnL (Profit and Loss), executed trade history, and a visual split of assets.
4. Historical Analytics Toggle:
   - A time-frame selector (1M, 5M, 15M, 1D) that alters chart rendering speeds and updates backtesting metrics.

[Implementation Rules]
- Act as an elite FinTech Software Engineer. Follow strict Clean Code principles.
- DO NOT truncate code. Complete every single React component, styling layout, utility function, and calculation helper.
- Ensure type safety or comprehensive vanilla JS configurations so the app mounts successfully without runtime errors or missing import failures.
- Provide clear setup instructions at the very beginning specifying exactly what npm packages to install.

Please properly file it into a folder and tell me how to run it, start generating now.