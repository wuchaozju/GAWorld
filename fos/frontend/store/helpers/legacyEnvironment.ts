import type { Agent, LogEntry } from '../../types';

export const fetchEnvironmentSuggestions = async (
  logs: LogEntry[],
  agents: Agent[],
): Promise<Array<{ event: string; reason: string }>> => {
  const apiKey =
    (import.meta as any).env?.VITE_GEMINI_API_KEY ||
    (window as any).GEMINI_API_KEY ||
    process.env.API_KEY ||
    '';

  if (!apiKey) {
    throw new Error('No API Key - Please set VITE_GEMINI_API_KEY environment variable');
  }

  const { GoogleGenAI, Type } = await import('@google/genai');
  const ai = new GoogleGenAI({ apiKey });
  const recentLogs = logs.slice(-15).map((log) => `[${log.type}] ${log.content}`).join('\n');
  const agentSummary = agents.map((agent) => `${agent.name}(${agent.role})`).join(', ');

  try {
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: `Based on the recent simulation logs, suggest 3 potential environment events that could happen next to drive the narrative or challenge the agents.

      Recent Logs:
      ${recentLogs}

      Agents involved: ${agentSummary}`,
      config: {
        systemInstruction: 'You are a dynamic environment simulator. Propose realistic or dramatic environmental changes.',
        responseMimeType: 'application/json',
        responseSchema: {
          type: Type.ARRAY,
          items: {
            type: Type.OBJECT,
            properties: {
              event: { type: Type.STRING, description: 'The description of the event' },
              reason: { type: Type.STRING, description: 'Why this event fits the current context' },
            },
            required: ['event', 'reason'],
          },
        },
      },
    });

    const text = response.text;
    return text ? JSON.parse(text) : [];
  } catch (error) {
    console.error('Gemini Env Suggestion Error:', error);
    throw error;
  }
};
