import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { HealthStatus } from "@/types/api";

interface HealthPanelProps {
  health: HealthStatus;
}

export function HealthPanel({ health }: HealthPanelProps) {
  const isOk = health.status === "ok";

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            服务状态
            <Badge variant={isOk ? "default" : "destructive"}>
              {isOk ? "正常" : "降级"}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-muted-foreground">服务</dt>
              <dd className="font-medium">{health.service}</dd>
            </div>
            {health.litellm && (
              <div>
                <dt className="text-muted-foreground">LiteLLM</dt>
                <dd className="font-medium">{health.litellm}</dd>
              </div>
            )}
            {health.circuit_breaker && (
              <div>
                <dt className="text-muted-foreground">Circuit Breaker</dt>
                <dd className="font-medium">{health.circuit_breaker}</dd>
              </div>
            )}
            {health.redis && (
              <div>
                <dt className="text-muted-foreground">Redis</dt>
                <dd className="font-medium">{health.redis}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
